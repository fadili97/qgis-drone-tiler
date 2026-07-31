# Drone Tiler — QGIS plugin

Slice a GeoTIFF into a grid of **overlapping JPEG frames that mimic a UAV/drone photo survey**.
You give a satellite/ortho image; it returns individual "photos" laid out in a lawnmower
(serpentine) pattern with the forward and side overlap you specify.

Built as a **QGIS Processing algorithm**, so it shows up in the Processing Toolbox with a
parameter dialog and can be scripted or run in batch/headless.

## Install

**From ZIP (recommended)**

1. Zip the inner `drone_tiler` folder so the archive contains `drone_tiler/metadata.txt` at
   its root. In PowerShell, from the repo root:
   ```powershell
   Compress-Archive -Path drone_tiler -DestinationPath drone_tiler.zip -Force
   ```
2. QGIS → **Plugins → Manage and Install Plugins → Install from ZIP** → pick `drone_tiler.zip`.

**Manual**

Copy the `drone_tiler` folder into your QGIS plugins directory, then enable it in the Plugin
Manager:
```
%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\drone_tiler
```

## Use

Processing Toolbox → **Drone Tiler → Simulate drone frames from raster**.

| Parameter | Meaning | Default |
|---|---|---|
| Input raster (GeoTIFF) | North-up, georeferenced, 8-bit source | — |
| Frame ground width (m) | Footprint width of each "photo" on the ground | 60 |
| Frame ground height (m) | Footprint height | 45 |
| Forward (longitudinal) overlap % | Overlap along a flight line | 80 |
| Side (lateral) overlap % | Overlap between flight lines | 70 |
| Serpentine numbering | Number frames boustrophedon (snake) order | on |
| Keep partial edge frames | Also write clipped frames at the borders | off |
| JPEG quality | 1–100 | 90 |
| Output frame width / height in px | Resample each frame to this size; `0` = native 1:1 crop | 0 |
| Resampling | cubic / lanczos / bilinear / nearest (only when resizing) | cubic |
| Output folder | Where frames + manifest are written | — |

### Resizing vs. real resolution

Setting an output size lets frames match a real camera's dimensions — e.g. `5280 × 3956`
for a DJI Mavic 3E — which also pushes file sizes into the multi-megabyte range typical of
drone photos. **It adds no real detail:** the ground resolution stays that of the source
raster, the extra pixels are interpolated. To gain genuine pixels instead, enlarge the
ground footprint (more metres per frame) and leave the output size at `0`.

Frame pixel size and the step between frames are **derived** from the raster's own resolution
(GSD) and your overlaps — you don't set them:

```
frame_px   = frame_metres / GSD
step        = frame_px * (1 - overlap)
```

## Run without the QGIS GUI

The tiling logic lives in `drone_tiler/core.py` and has **no QGIS dependency** (GDAL only),
so it can be driven from the command line with QGIS's bundled Python:

```bat
"C:\Program Files\QGIS 3.44.11\bin\python-qgis-ltr.bat" scripts\run_tiler.py ^
    ortho_rgb.tif out_frames --frame-w 800 --frame-h 600 --fwd 75 --side 65 --quality 93
```

## DJI-style metadata (post-processing)

`scripts/add_metadata.py` turns a folder of frames into something that looks like a real
DJI download: it geotags each frame, renames it to the DJI convention and writes a `.MRK`
companion file.

```bat
"C:\Program Files\QGIS 3.44.11\bin\python-qgis-ltr.bat" scripts\add_metadata.py ^
    out_frames --source-raster ortho_rgb.tif --speed 15
```

It reads `frames.csv`, reprojects each frame centre to WGS84 and writes:

- **EXIF** — `Make`/`Model`, focal length, GPS latitude/longitude/altitude, `DateTimeOriginal`.
- **XMP** — a `drone-dji` block with absolute/relative altitude and gimbal angles. Yaw is
  derived from the bearing between consecutive frames on the same flight line, so it follows
  the serpentine.
- **Filenames** — `DJI_<YYYYMMDDHHMMSS>_<NNNN>_V.JPG`, worldfiles renamed to match.
- **`<flight>_Timestamp.MRK`** — one RTK-style position record per shot.

Flight altitude is not guessed: it is the altitude at which a Mavic 3E would produce exactly
this ground footprint, computed from the manifest. `--speed` sets the shot interval from the
real spacing between frames (otherwise `--interval` seconds is used).

The JPEG pixel data is **not re-encoded** — segments are spliced in, so enriching costs no
extra quality and takes minutes rather than hours.

## Output

- `frame_0001.jpg`, `frame_0002.jpg`, … — the individual frames.
- A `.wld` world file next to each frame, so you can drag them back into QGIS and see them
  tile in place (a reconstructed "drone mosaic").
- `frames.csv` — a manifest with each frame's row/col, centre and bounding box in map units.

## Notes / limits

- **Visual mock-up tool.** Frames are clean orthorectified crops — no perspective, tilt, lens
  distortion or GPS jitter, and no EXIF geotags. It does not produce imagery for real
  photogrammetry reconstruction.
- Requires a **north-up**, **georeferenced**, **8-bit (Byte)** raster. Convert others first, e.g.
  `gdal_translate -ot Byte -scale src.tif src_8bit.tif`.
- Rasters with 3+ bands are written as RGB (bands 1–3); a single band is written as greyscale.

## License

MIT — see [LICENSE](LICENSE).
