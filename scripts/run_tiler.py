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
    p.add_argument('--keep-partial', action='store_true', help='keep partial edge frames')
    p.add_argument('--no-serpentine', action='store_true', help='row-major numbering')
    args = p.parse_args()

    def progress(pct):
        sys.stdout.write('\r  %3d%%' % pct)
        sys.stdout.flush()

    try:
        r = tile_raster(
            args.input, args.output_dir,
            frame_w_m=args.frame_w, frame_h_m=args.frame_h,
            fwd_overlap=args.fwd, side_overlap=args.side,
            serpentine=not args.no_serpentine,
            keep_partial=args.keep_partial, quality=args.quality,
            log=lambda m: print(m), progress=progress,
        )
    except TilerError as e:
        print('ERROR: %s' % e)
        return 1
    print('\nOK — %d frames' % r['count'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
