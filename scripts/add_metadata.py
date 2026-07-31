# -*- coding: utf-8 -*-
"""Add DJI-style EXIF/XMP geotags to frames produced by Drone Tiler,
rename them to the DJI convention and write a .MRK companion file.

Works in place on existing frames — the JPEG pixel data is not re-encoded.

Usage (with QGIS's python):
  python-qgis-ltr.bat scripts/add_metadata.py FRAMES_DIR --source-raster ortho_rgb.tif
"""
import os
import sys
import csv
import math
import time
import argparse
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from drone_tiler.exif import build_exif, build_xmp, inject  # noqa: E402

from osgeo import gdal, osr  # noqa: E402

# DJI Mavic 3E wide camera
CALIBRATED_FOCAL_PX = 3725.151611
FOCAL_MM = 12.29
FOCAL_35 = 24


def retry(fn, *a, **kw):
    """Windows: an antivirus scan or an open QGIS layer can hold a brief lock."""
    for attempt in range(8):
        try:
            return fn(*a, **kw)
        except OSError:
            if attempt == 7:
                raise
            time.sleep(0.4 * (attempt + 1))


def _write(path, data):
    with open(path, 'wb') as f:
        f.write(data)


def bearing(x1, y1, x2, y2):
    """Bearing in degrees from north, normalised to -180..180 (DJI style)."""
    b = math.degrees(math.atan2(x2 - x1, y2 - y1))
    return (b + 180.0) % 360.0 - 180.0


def main():
    p = argparse.ArgumentParser()
    p.add_argument('frames_dir')
    p.add_argument('--source-raster', required=True, help='to read the CRS from')
    p.add_argument('--start-time', default='2026-07-14 18:29:56')
    p.add_argument('--interval', type=float, default=2.0, help='seconds between shots')
    p.add_argument('--speed', type=float, default=0.0,
                   help='ground speed m/s; overrides --interval using real frame spacing')
    p.add_argument('--ground-alt', type=float, default=0.0,
                   help='terrain elevation (m) used for AbsoluteAltitude')
    p.add_argument('--rel-alt', type=float, default=0.0,
                   help='force flight altitude (m) instead of deriving it from the '
                        'frame footprint; the two then no longer agree geometrically')
    p.add_argument('--model', default='M3E')
    p.add_argument('--no-rename', action='store_true')
    args = p.parse_args()

    ds = gdal.Open(args.source_raster)
    if ds is None:
        print('ERROR: cannot open %s' % args.source_raster)
        return 1
    src_srs = osr.SpatialReference()
    src_srs.ImportFromWkt(ds.GetProjection())
    src_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst_srs = osr.SpatialReference()
    dst_srs.ImportFromEPSG(4326)
    dst_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct = osr.CoordinateTransformation(src_srs, dst_srs)
    ds = None

    manifest = os.path.join(args.frames_dir, 'frames.csv')
    with open(manifest, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print('ERROR: empty manifest')
        return 1

    # relative altitude that reproduces this ground footprint with the M3E lens
    gw = float(rows[0]['max_x']) - float(rows[0]['min_x'])
    gsd = gw / float(rows[0]['width_px'])
    rel_alt = gsd * CALIBRATED_FOCAL_PX
    print('GSD sortie : %.4f m/px  ->  altitude equivalente M3E : %.1f m' % (gsd, rel_alt))
    if args.rel_alt > 0:
        print('Altitude forcee a %.1f m (emprise %.0f m ; la geometrie M3E impliquerait '
              '%.0f m -> valeurs non concordantes, voulu)'
              % (args.rel_alt, gw, rel_alt))
        rel_alt = args.rel_alt
    abs_alt = args.ground_alt + rel_alt

    if args.speed > 0 and len(rows) > 1 and rows[1]['row'] == rows[0]['row']:
        spacing = math.hypot(float(rows[1]['center_x']) - float(rows[0]['center_x']),
                             float(rows[1]['center_y']) - float(rows[0]['center_y']))
        args.interval = spacing / args.speed
        print('Espacement %.0f m a %.1f m/s -> intervalle %.1f s'
              % (spacing, args.speed, args.interval))

    t0 = datetime.datetime.strptime(args.start_time, '%Y-%m-%d %H:%M:%S')

    # yaw from the next frame on the same flight line (fall back to previous)
    def yaw_for(i):
        r = rows[i]
        for j in (i + 1, i - 1):
            if 0 <= j < len(rows) and rows[j]['row'] == r['row']:
                a, b = (r, rows[j]) if j > i else (rows[j], r)
                return bearing(float(a['center_x']), float(a['center_y']),
                               float(b['center_x']), float(b['center_y']))
        return 0.0

    mrk_lines = []
    out_rows = []
    locked = []
    n = len(rows)
    for i, r in enumerate(rows):
        src = os.path.join(args.frames_dir, r['filename'])
        if not os.path.exists(src):
            print('manquant: %s' % r['filename'])
            continue

        lon, lat, _ = ct.TransformPoint(float(r['center_x']), float(r['center_y']))
        shot = t0 + datetime.timedelta(seconds=args.interval * i)
        stamp = shot.strftime('%Y:%m:%d %H:%M:%S')
        yaw = yaw_for(i)

        with open(src, 'rb') as f:
            data = f.read()
        data = inject(data, [
            build_exif(model=args.model, datetime_str=stamp,
                       lat=lat, lon=lon, alt=abs_alt,
                       focal_mm=FOCAL_MM, focal_35=FOCAL_35,
                       width=int(r['width_px']), height=int(r['height_px'])),
            build_xmp(lat, lon, abs_alt, rel_alt, yaw),
        ])

        if args.no_rename:
            dst_name = r['filename']
        else:
            dst_name = 'DJI_%s_%04d_V.JPG' % (shot.strftime('%Y%m%d%H%M%S'), i + 1)
        dst = os.path.join(args.frames_dir, dst_name)

        # the flight record is known whether or not the write succeeds, so fill
        # it in first — a locked file must not punch a hole in MRK/manifest
        mrk_lines.append(
            '%d\t%.6f\t[%d]\t     0,N\t     0,E\t     0,V\t'
            '%.8f,Lat\t%.8f,Lon\t%.3f,Ellh\t0.000000, 0.000000, 0.000000\t1,Q'
            % (i + 1, args.interval * i, 2374, lat, lon, abs_alt))

        written_ok = True
        try:
            retry(_write, dst, data)
        except OSError:
            # held by another process (an open QGIS layer, antivirus): skip it,
            # report at the end, let the user re-run for these only
            locked.append(r['filename'])
            written_ok = False

        if written_ok:
            if dst_name != r['filename']:
                retry(os.remove, src)
                old_wld = os.path.splitext(src)[0] + '.wld'
                if os.path.exists(old_wld):
                    retry(os.replace, old_wld, os.path.splitext(dst)[0] + '.wld')
                aux = src + '.aux.xml'
                if os.path.exists(aux):
                    retry(os.remove, aux)
            r['filename'] = dst_name

        r['lat'] = '%.9f' % lat
        r['lon'] = '%.9f' % lon
        r['rel_alt'] = '%.3f' % rel_alt
        r['yaw'] = '%.2f' % yaw
        r['datetime'] = stamp
        out_rows.append(r)

        if (i + 1) % 100 == 0 or i + 1 == n:
            sys.stdout.write('\r  %d/%d' % (i + 1, n))
            sys.stdout.flush()

    base = os.path.basename(os.path.dirname(args.frames_dir.rstrip('\\/'))) or 'FLIGHT'
    mrk = os.path.join(args.frames_dir, '%s_Timestamp.MRK' % base)
    with open(mrk, 'w', encoding='ascii') as f:
        f.write('\n'.join(mrk_lines) + '\n')

    with open(manifest, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    print('\nOK — %d/%d frames enrichies | MRK: %s'
          % (len(out_rows) - len(locked), len(out_rows), os.path.basename(mrk)))
    if locked:
        print('VERROUILLEES (non reecrites), fermer QGIS et relancer : %d' % len(locked))
        for name in locked[:10]:
            print('   %s' % name)
        if len(locked) > 10:
            print('   ... et %d autres' % (len(locked) - 10))
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
