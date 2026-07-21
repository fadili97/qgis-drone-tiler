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
| Output folder | Where frames + manifest are written | — |

Frame pixel size and the step between frames are **derived** from the raster's own resolution
(GSD) and your overlaps — you don't set them:

```
frame_px   = frame_metres / GSD
step        = frame_px * (1 - overlap)
```

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
