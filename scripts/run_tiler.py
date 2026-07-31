# -*- coding: utf-8 -*-
"""Run Drone Tiler from the command line (no QGIS GUI needed).

Usage (with QGIS's python):
  python-qgis-ltr.bat scripts/run_tiler.py INPUT.tif OUTPUT_DIR \
      --frame-w 800 --frame-h 600 --fwd 75 --side 65 --quality 93
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from drone_tiler.core import tile_raster, TilerError  # noqa: E402


def main():
    p = argparse.ArgumentParser(description='Slice a GeoTIFF into UAV-style frames.')
    p.add_argument('input')
    p.add_argument('output_dir')
    p.add_argument('--frame-w', type=float, required=True, help='frame ground width (m)')
    p.add_argument('--frame-h', type=float, required=True, help='frame ground height (m)')
    p.add_argument('--fwd', type=float, default=80.0, help='forward overlap %%')
    p.add_argument('--side', type=float, default=70.0, help='side overlap %%')
    p.add_argument('--quality', type=int, default=90, help='JPEG quality')
    p.add_argument('--out-w', type=int, default=0, help='output width px (0 = native)')
    p.add_argument('--out-h', type=int, default=0, help='output height px (0 = native)')
    p.add_argument('--resample', default='cubic',
                   choices=['cubic', 'lanczos', 'bilinear', 'nearest'])
    p.add_argument('--tone-ref', help='folder of real drone photos to match')
    p.add_argument('--vignette', type=float, default=0.5,
                   help='corner falloff, 0 = off (0.5 = corners at 50%%)')
    p.add_argument('--jitter', type=float, default=0.045,
                   help='per-frame exposure variation, 0 = off')
    p.add_argument('--grain', type=float, default=0.0, help='noise sigma, 0 = off')
    p.add_argument('--keep-partial', action='store_true', help='keep partial edge frames')
    p.add_argument('--no-serpentine', action='store_true', help='row-major numbering')
    args = p.parse_args()

    def progress(pct):
        sys.stdout.write('\r  %3d%%' % pct)
        sys.stdout.flush()

    matcher = None
    if args.tone_ref:
        from drone_tiler.tone import measure_reference, measure_raster, ToneMatcher
        ref = measure_reference(args.tone_ref)
        print('reference : %d photos nadir sur %d | lum=%.1f ecart-type=%.1f sat=%.1f%%'
              % (ref['nadir'], ref['total'], ref['lum_mean'], ref['lum_std'], ref['sat']))
        # measure at frame scale, not whole-ortho scale (contrast is scale-dependent)
        from osgeo import gdal
        _ds = gdal.Open(args.input)
        _gt = _ds.GetGeoTransform()
        _fw = max(1, int(round(args.frame_w / abs(_gt[1]))))
        _fh = max(1, int(round(args.frame_h / abs(_gt[5]))))
        _ds = None
        src_stats = measure_raster(args.input, frame_px=(_fw, _fh))
        print('ortho     : lum=%.1f ecart-type=%.1f sat=%.1f%% (mesure sur %d fenetres '
              'de %dx%d px)' % (src_stats['lum_mean'], src_stats['lum_std'],
                                src_stats['sat'], src_stats['n'], _fw, _fh))
        matcher = ToneMatcher(ref, src_stats, vignette=args.vignette,
                              jitter=args.jitter, grain=args.grain)
        print('correction: %s' % matcher.describe())

    try:
        r = tile_raster(
            args.input, args.output_dir,
            frame_w_m=args.frame_w, frame_h_m=args.frame_h,
            fwd_overlap=args.fwd, side_overlap=args.side,
            serpentine=not args.no_serpentine,
            keep_partial=args.keep_partial, quality=args.quality,
            out_w=args.out_w, out_h=args.out_h, resample=args.resample,
            matcher=matcher,
            log=lambda m: print(m), progress=progress,
        )
    except TilerError as e:
        print('ERROR: %s' % e)
        return 1
    print('\nOK — %d frames' % r['count'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
