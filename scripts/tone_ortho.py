# -*- coding: utf-8 -*-
"""Apply the drone tone match to a whole orthomosaic, writing a corrected RGB GeoTIFF.

Only the tonal part is applied here. Vignetting and exposure jitter are
deliberately excluded: they are per-photo effects, and baking them into an
ortho would stamp a dark blob in the middle of the map. Add them later, at
tiling time, with run_tiler.py --vignette/--jitter.

The contrast gain is measured at *frame* scale, so frames cut from the
corrected ortho land on the drone target.

Usage (with QGIS's python):
  python-qgis-ltr.bat scripts/tone_ortho.py IN.tif OUT.tif \
      --tone-ref "path/to/DJI_photos" --frame-w 800 --frame-h 600
"""
import os
import sys
import argparse

import numpy as np
from osgeo import gdal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from drone_tiler.tone import measure_reference, measure_raster, _lum  # noqa: E402

gdal.UseExceptions()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('input')
    p.add_argument('output')
    p.add_argument('--tone-ref', required=True)
    p.add_argument('--frame-w', type=float, default=800.0,
                   help='frame ground width (m) the gain is calibrated for')
    p.add_argument('--frame-h', type=float, default=600.0)
    p.add_argument('--block', type=int, default=512, help='rows per block')
    p.add_argument('--compress', default='NONE')
    args = p.parse_args()

    ds = gdal.Open(args.input)
    gt = ds.GetGeoTransform()
    W, H = ds.RasterXSize, ds.RasterYSize
    nb = min(3, ds.RasterCount)

    ref = measure_reference(args.tone_ref)
    print('reference : %d nadir / %d photos | lum=%.1f ecart-type=%.1f sat=%.1f%%'
          % (ref['nadir'], ref['total'], ref['lum_mean'], ref['lum_std'], ref['sat']))

    fw = max(1, int(round(args.frame_w / abs(gt[1]))))
    fh = max(1, int(round(args.frame_h / abs(gt[5]))))
    src = measure_raster(args.input, frame_px=(fw, fh))
    print('ortho     : lum=%.1f ecart-type=%.1f sat=%.1f%% (mesure sur %d fenetres '
          'de %dx%d px)' % (src['lum_mean'], src['lum_std'], src['sat'],
                            src['n'], fw, fh))

    gain = ref['lum_std'] / max(src['lum_std'], 1e-6)
    sat_gain = ref['sat'] / max(src['sat'], 1e-6)
    print('correction: contraste x%.2f | luminosite %.1f -> %.1f | saturation x%.2f'
          % (gain, src['lum_mean'], ref['lum_mean'], sat_gain))
    print('            (pas de vignettage ni de jitter : effets par photo)')

    drv = gdal.GetDriverByName('GTiff')
    opts = ['TILED=YES', 'BLOCKXSIZE=512', 'BLOCKYSIZE=512',
            'COMPRESS=%s' % args.compress, 'BIGTIFF=IF_SAFER',
            'NUM_THREADS=ALL_CPUS']
    out = drv.Create(args.output, W, H, 3, gdal.GDT_Byte, options=opts)
    out.SetGeoTransform(gt)
    out.SetProjection(ds.GetProjection())

    lo_clip = hi_clip = total = 0
    for y in range(0, H, args.block):
        rows = min(args.block, H - y)
        a = np.stack([ds.GetRasterBand(b + 1).ReadAsArray(0, y, W, rows)
                      for b in range(nb)]).astype(np.float32)
        if a.shape[0] == 1:
            a = np.repeat(a, 3, axis=0)

        l0 = _lum(a)
        l1 = (l0 - src['lum_mean']) * gain + ref['lum_mean']
        a = a * (l1 / np.maximum(l0, 1e-6))
        if abs(sat_gain - 1.0) > 1e-3:
            g = _lum(a)
            a = g + (a - g) * sat_gain

        lo_clip += int((a < 0).sum())
        hi_clip += int((a > 255).sum())
        total += a.size
        a = np.clip(a, 0, 255)

        for c in range(3):
            out.GetRasterBand(c + 1).WriteArray(a[c].astype('uint8'), 0, y)
        sys.stdout.write('\r  %d/%d lignes (%d%%)' % (y + rows, H, 100 * (y + rows) // H))
        sys.stdout.flush()

    out.FlushCache()
    out = None
    ds = None
    print('\necretage : %.2f%% bas / %.2f%% haut'
          % (100.0 * lo_clip / total, 100.0 * hi_clip / total))
    print('ecrit : %s (%.1f Go)'
          % (args.output, os.path.getsize(args.output) / 1024.0 ** 3))
    return 0


if __name__ == '__main__':
    sys.exit(main())
