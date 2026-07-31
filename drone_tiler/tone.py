# -*- coding: utf-8 -*-
"""Make orthomosaic crops look like drone frames.

An orthomosaic is atmospherically normalised and blended, so it is flat, often
too bright and over-saturated, and it has no lens signature. This module
measures a reference set of real drone photos and reshapes crops to match.

Luminance is stretched on its own and the R:G:B ratios are preserved —
stretching each channel independently wrecks the hues (haze compresses blue far
more than red, so independent gains produce a magenta cast).
"""
import os
import glob

import numpy as np
from osgeo import gdal

W_R, W_G, W_B = 0.299, 0.587, 0.114


def _lum(a):
    return W_R * a[0] + W_G * a[1] + W_B * a[2]


def _sat(a):
    mx = np.maximum(np.maximum(a[0], a[1]), a[2])
    mn = np.minimum(np.minimum(a[0], a[1]), a[2])
    return float(np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0).mean() * 100)


def _read_rgb(path, target_w):
    ds = gdal.Open(path)
    if ds is None:
        raise IOError('cannot open %s' % path)
    W, H = ds.RasterXSize, ds.RasterYSize
    bw = min(target_w, W)
    bh = max(1, int(H * bw / W))
    a = np.stack([ds.GetRasterBand(b).ReadAsArray(0, 0, W, H, buf_xsize=bw,
                                                  buf_ysize=bh) for b in (1, 2, 3)])
    alpha = None
    if ds.RasterCount >= 4:
        alpha = ds.GetRasterBand(4).ReadAsArray(0, 0, W, H, buf_xsize=bw, buf_ysize=bh)
    ds = None
    return a.astype(np.float32), alpha


def _gimbal_pitch(path):
    try:
        with open(path, 'rb') as f:
            t = f.read(60000).decode('ascii', 'ignore')
    except IOError:
        return None
    k = 'drone-dji:GimbalPitchDegree="'
    i = t.find(k)
    return None if i < 0 else float(t[i + len(k):t.find('"', i + len(k))])


def measure_reference(folder, max_photos=25, nadir_below=-80.0):
    """Tonal profile of real drone photos. Oblique shots are skipped: they
    contain sky and horizon and are not comparable with a nadir crop."""
    # dedup: on a case-insensitive filesystem *.JPG and *.jpg return the same files
    seen = {}
    for pat in ('*.JPG', '*.jpg'):
        for f in glob.glob(os.path.join(folder, pat)):
            seen[os.path.normcase(os.path.abspath(f))] = f
    files = sorted(seen.values())
    nadir = [f for f in files if (_gimbal_pitch(f) or 0.0) < nadir_below]
    pool = nadir or files
    sel = pool[::max(1, len(pool) // max_photos)][:max_photos]
    if not sel:
        raise IOError('no reference photo found in %s' % folder)
    means, stds, sats = [], [], []
    for f in sel:
        a, _ = _read_rgb(f, 500)
        l = _lum(a)
        means.append(float(l.mean()))
        stds.append(float(l.std()))
        sats.append(_sat(a))
    return {'lum_mean': float(np.mean(means)), 'lum_std': float(np.mean(stds)),
            'sat': float(np.mean(sats)), 'n': len(sel),
            'nadir': len(nadir), 'total': len(files),
            'spread': (float(np.min(means)), float(np.max(means)))}


def measure_raster(path, target_w=1200, frame_px=None, samples=24, seed=12345):
    """Tonal profile of the source raster.

    With frame_px=(w, h) the statistics are measured on frame-sized windows
    instead of the whole image. This matters: contrast is scale-dependent, and
    a whole-ortho standard deviation mixes in variation between distant areas
    that no single frame ever sees — using it under-estimates the gain a frame
    actually needs, by a factor of ~2 in practice.
    """
    if frame_px is None:
        a, alpha = _read_rgb(path, target_w)
        if alpha is not None and (alpha > 0).any():
            a = np.stack([c[alpha > 0] for c in a])
        l = _lum(a)
        return {'lum_mean': float(l.mean()), 'lum_std': float(l.std()), 'sat': _sat(a)}

    fw, fh = frame_px
    ds = gdal.Open(path)
    if ds is None:
        raise IOError('cannot open %s' % path)
    W, H = ds.RasterXSize, ds.RasterYSize
    fw, fh = min(fw, W), min(fh, H)
    rng = np.random.RandomState(seed)
    nb = min(3, ds.RasterCount)
    means, stds, sats = [], [], []
    for _ in range(samples):
        xo = int(rng.randint(0, max(1, W - fw + 1)))
        yo = int(rng.randint(0, max(1, H - fh + 1)))
        bw = min(400, fw)
        bh = max(1, int(fh * bw / fw))
        a = np.stack([ds.GetRasterBand(b + 1).ReadAsArray(xo, yo, fw, fh,
                                                          buf_xsize=bw, buf_ysize=bh)
                      for b in range(nb)]).astype(np.float32)
        if a.shape[0] == 1:
            a = np.repeat(a, 3, axis=0)
        if ds.RasterCount >= 4:
            al = ds.GetRasterBand(4).ReadAsArray(xo, yo, fw, fh, buf_xsize=bw,
                                                 buf_ysize=bh)
            if (al > 0).mean() < 0.9:      # mostly empty window, skip it
                continue
        l = _lum(a)
        means.append(float(l.mean()))
        stds.append(float(l.std()))
        sats.append(_sat(a))
    ds = None
    if not means:
        raise IOError('no usable sample window in %s' % path)
    return {'lum_mean': float(np.mean(means)), 'lum_std': float(np.mean(stds)),
            'sat': float(np.mean(sats)), 'n': len(means)}


def vignette_mask(h, w, strength=0.5, r0=1.15, power=3.0):
    """Radial falloff fitted to the measured M3E profile: flat across the frame,
    then a fast drop confined to the extreme corners (~50% at r=1.41)."""
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt(((xx - w / 2.0) / (w / 2.0)) ** 2 + ((yy - h / 2.0) / (h / 2.0)) ** 2)
    r_max = float(np.sqrt(2.0))
    t = np.clip((r - r0) / max(r_max - r0, 1e-6), 0.0, 1.0)
    return (1.0 - strength * t ** power).astype(np.float32)


class ToneMatcher(object):
    def __init__(self, ref, src, vignette=0.5, jitter=0.0, grain=0.0):
        self.ref = ref
        self.src = src
        self.gain = ref['lum_std'] / max(src['lum_std'], 1e-6)
        self.sat_gain = ref['sat'] / max(src['sat'], 1e-6)
        self.vignette = vignette
        self.jitter = jitter
        self.grain = grain
        self._mask = None
        self._mask_shape = None

    def describe(self):
        return ('contraste x%.2f | luminosite %.1f -> %.1f | saturation x%.2f'
                % (self.gain, self.src['lum_mean'], self.ref['lum_mean'],
                   self.sat_gain))

    def _vig(self, h, w):
        if self._mask_shape != (h, w):
            self._mask = vignette_mask(h, w, self.vignette)
            self._mask_shape = (h, w)
        return self._mask

    def apply(self, arr, index=0):
        """arr: float32 (3, h, w) in 0..255. Returns the corrected array."""
        a = arr
        l0 = _lum(a)
        l1 = (l0 - self.src['lum_mean']) * self.gain + self.ref['lum_mean']

        if self.jitter:
            # each real frame has its own exposure; reproduce that spread
            rng = np.random.RandomState(index * 2654435761 % (2 ** 31))
            l1 = l1 * (1.0 + rng.uniform(-self.jitter, self.jitter))

        a = a * (l1 / np.maximum(l0, 1e-6))

        if abs(self.sat_gain - 1.0) > 1e-3:
            g = _lum(a)
            a = g + (a - g) * self.sat_gain

        if self.vignette:
            a = a * self._vig(a.shape[1], a.shape[2])

        if self.grain:
            rng = np.random.RandomState((index * 40503 + 7) % (2 ** 31))
            a = a + rng.normal(0.0, self.grain, a.shape).astype(np.float32)

        return np.clip(a, 0, 255)
