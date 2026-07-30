# -*- coding: utf-8 -*-
"""Tiling logic — pure GDAL, no QGIS imports, so it also runs standalone."""
import os
import csv

from osgeo import gdal


class TilerError(Exception):
    pass


def frame_grid(width, height, frame_w, frame_h, step_x, step_y, serpentine=True):
    """Offsets of every frame, in lawnmower order."""
    def offsets(total, frame, step):
        offs, o = [], 0
        while o < total:
            offs.append(o)
            if o + frame >= total:
                break
            o += step
        return offs

    x_offs = offsets(width, frame_w, step_x)
    y_offs = offsets(height, frame_h, step_y)

    frames = []
    for ri, yoff in enumerate(y_offs):
        cols = list(enumerate(x_offs))
        if serpentine and ri % 2 == 1:
            cols = list(reversed(cols))
        for ci, xoff in cols:
            frames.append((ri, ci, xoff, yoff))
    return frames


def tile_raster(src, out_dir, frame_w_m, frame_h_m, fwd_overlap, side_overlap,
                serpentine=True, keep_partial=False, quality=90,
                out_w=0, out_h=0, resample='cubic',
                log=None, progress=None, is_canceled=None):
    """Slice `src` into overlapping JPEG frames. Returns a summary dict.

    out_w/out_h resample each frame to that pixel size (0 = keep native, i.e. a
    1:1 crop). Upscaling matches real camera dimensions but adds no real detail —
    the ground resolution stays that of the source raster.
    """
    log = log or (lambda m: None)
    ds = gdal.Open(src)
    if ds is None:
        raise TilerError('Could not open raster with GDAL.')

    gt = ds.GetGeoTransform()
    if gt is None or gt[2] != 0 or gt[4] != 0:
        raise TilerError('Only north-up (unrotated) GeoTIFFs are supported.')
    px, py = abs(gt[1]), abs(gt[5])
    if px == 0 or py == 0:
        raise TilerError('Raster has no valid pixel size — is it georeferenced?')
    if ds.GetRasterBand(1).DataType != gdal.GDT_Byte:
        raise TilerError('JPEG output needs an 8-bit (Byte) raster. Convert it '
                         'first, e.g. gdal_translate -ot Byte -scale.')

    W, H = ds.RasterXSize, ds.RasterYSize
    band_list = [1, 2, 3] if ds.RasterCount >= 3 else list(range(1, ds.RasterCount + 1))

    fw = max(1, int(round(frame_w_m / px)))
    fh = max(1, int(round(frame_h_m / py)))
    step_x = max(1, int(round(fw * (1.0 - side_overlap / 100.0))))
    step_y = max(1, int(round(fh * (1.0 - fwd_overlap / 100.0))))

    frames = frame_grid(W, H, fw, fh, step_x, step_y, serpentine)
    total = len(frames)
    log('GSD: %.4f x %.4f m/px' % (px, py))
    log('Frame: %d x %d px | step: %d x %d px | grid up to %d frame(s)'
        % (fw, fh, step_x, step_y, total))
    if out_w and out_h:
        log('Output resampled to %d x %d px (%s) — no added detail, GSD unchanged'
            % (out_w, out_h, resample))

    os.makedirs(out_dir, exist_ok=True)
    manifest = os.path.join(out_dir, 'frames.csv')
    written = 0
    with open(manifest, 'w', newline='', encoding='utf-8') as mf:
        writer = csv.writer(mf)
        writer.writerow(['frame', 'filename', 'row', 'col',
                         'center_x', 'center_y',
                         'min_x', 'min_y', 'max_x', 'max_y',
                         'width_px', 'height_px'])
        for (ri, ci, xoff, yoff) in frames:
            if is_canceled and is_canceled():
                break
            xsize, ysize = fw, fh
            if xoff + xsize > W or yoff + ysize > H:
                if not keep_partial:
                    continue
                xsize = min(xsize, W - xoff)
                ysize = min(ysize, H - yoff)

            written += 1
            name = 'frame_%04d.jpg' % written
            kw = {}
            if out_w and out_h:
                # scale proportionally so partial edge frames are not stretched
                kw = {'width': max(1, int(round(out_w * xsize / float(fw)))),
                      'height': max(1, int(round(out_h * ysize / float(fh)))),
                      'resampleAlg': resample}
            out_ds = gdal.Translate(
                os.path.join(out_dir, name), ds,
                srcWin=[xoff, yoff, xsize, ysize],
                format='JPEG', bandList=band_list,
                creationOptions=['QUALITY=%d' % quality, 'WORLDFILE=YES'],
                **kw
            )
            if out_ds is None:
                raise TilerError('GDAL failed to write %s' % name)
            out_ds = None

            min_x = gt[0] + xoff * gt[1]
            max_x = gt[0] + (xoff + xsize) * gt[1]
            max_y = gt[3] + yoff * gt[5]
            min_y = gt[3] + (yoff + ysize) * gt[5]
            writer.writerow([
                written, name, ri, ci,
                '%.3f' % ((min_x + max_x) / 2.0), '%.3f' % ((min_y + max_y) / 2.0),
                '%.3f' % min_x, '%.3f' % min_y, '%.3f' % max_x, '%.3f' % max_y,
                kw.get('width', xsize), kw.get('height', ysize),
            ])
            if progress and total:
                progress(int(100 * written / total))

    ds = None
    if written == 0:
        raise TilerError('No complete frame fits — the frame footprint is larger '
                         'than the raster. Reduce the frame size or enable '
                         '"Keep partial edge frames".')
    log('Wrote %d frame(s) to %s' % (written, out_dir))
    return {'count': written, 'manifest': manifest,
            'frame_px': (fw, fh), 'step_px': (step_x, step_y), 'gsd': (px, py)}
