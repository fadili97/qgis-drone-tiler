# -*- coding: utf-8 -*-
"""Slice a north-up GeoTIFF into overlapping JPEG frames that mimic a
UAV/drone photo survey (lawnmower grid)."""
import os
import csv

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFolderDestination,
)
from osgeo import gdal


class DroneTilerAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    FRAME_W = 'FRAME_W'
    FRAME_H = 'FRAME_H'
    FWD_OVERLAP = 'FWD_OVERLAP'
    SIDE_OVERLAP = 'SIDE_OVERLAP'
    SERPENTINE = 'SERPENTINE'
    KEEP_PARTIAL = 'KEEP_PARTIAL'
    QUALITY = 'QUALITY'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.INPUT, self.tr('Input raster (GeoTIFF)')))
        self.addParameter(QgsProcessingParameterNumber(
            self.FRAME_W, self.tr('Frame ground width (m)'),
            QgsProcessingParameterNumber.Double, 60.0, minValue=0.01))
        self.addParameter(QgsProcessingParameterNumber(
            self.FRAME_H, self.tr('Frame ground height (m)'),
            QgsProcessingParameterNumber.Double, 45.0, minValue=0.01))
        self.addParameter(QgsProcessingParameterNumber(
            self.FWD_OVERLAP, self.tr('Forward (longitudinal) overlap (%)'),
            QgsProcessingParameterNumber.Double, 80.0, minValue=0.0, maxValue=95.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.SIDE_OVERLAP, self.tr('Side (lateral) overlap (%)'),
            QgsProcessingParameterNumber.Double, 70.0, minValue=0.0, maxValue=95.0))
        self.addParameter(QgsProcessingParameterBoolean(
            self.SERPENTINE, self.tr('Serpentine (lawnmower) numbering'), True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.KEEP_PARTIAL, self.tr('Keep partial edge frames'), False))
        self.addParameter(QgsProcessingParameterNumber(
            self.QUALITY, self.tr('JPEG quality'),
            QgsProcessingParameterNumber.Integer, 90, minValue=1, maxValue=100))
        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUTPUT, self.tr('Output folder')))

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        if layer is None:
            raise QgsProcessingException(self.tr('Invalid input raster.'))
        src = layer.source()

        frame_w_m = self.parameterAsDouble(parameters, self.FRAME_W, context)
        frame_h_m = self.parameterAsDouble(parameters, self.FRAME_H, context)
        fwd = self.parameterAsDouble(parameters, self.FWD_OVERLAP, context)
        side = self.parameterAsDouble(parameters, self.SIDE_OVERLAP, context)
        serpentine = self.parameterAsBool(parameters, self.SERPENTINE, context)
        keep_partial = self.parameterAsBool(parameters, self.KEEP_PARTIAL, context)
        quality = self.parameterAsInt(parameters, self.QUALITY, context)
        out_dir = self.parameterAsString(parameters, self.OUTPUT, context)
        os.makedirs(out_dir, exist_ok=True)

        ds = gdal.Open(src)
        if ds is None:
            raise QgsProcessingException(self.tr('Could not open raster with GDAL.'))

        gt = ds.GetGeoTransform()
        if gt is None or gt[2] != 0 or gt[4] != 0:
            raise QgsProcessingException(self.tr(
                'Only north-up (unrotated) GeoTIFFs are supported.'))
        px = abs(gt[1])
        py = abs(gt[5])
        if px == 0 or py == 0:
            raise QgsProcessingException(self.tr(
                'Raster has no valid pixel size — is it georeferenced?'))

        if ds.GetRasterBand(1).DataType != gdal.GDT_Byte:
            raise QgsProcessingException(self.tr(
                'JPEG output needs an 8-bit (Byte) raster. Convert it first, e.g. '
                'gdal_translate -ot Byte -scale.'))

        W = ds.RasterXSize
        H = ds.RasterYSize
        band_count = ds.RasterCount
        band_list = [1, 2, 3] if band_count >= 3 else list(range(1, band_count + 1))

        fw = max(1, int(round(frame_w_m / px)))
        fh = max(1, int(round(frame_h_m / py)))
        step_x = max(1, int(round(fw * (1.0 - side / 100.0))))
        step_y = max(1, int(round(fh * (1.0 - fwd / 100.0))))

        def offsets(total, frame, step):
            offs, o = [], 0
            while o < total:
                offs.append(o)
                if o + frame >= total:
                    break
                o += step
            return offs

        x_offs = offsets(W, fw, step_x)
        y_offs = offsets(H, fh, step_y)

        # build ordered frame list (serpentine flips alternate rows)
        frames = []
        for ri, yoff in enumerate(y_offs):
            cols = list(enumerate(x_offs))
            if serpentine and ri % 2 == 1:
                cols = list(reversed(cols))
            for ci, xoff in cols:
                frames.append((ri, ci, xoff, yoff))

        total = len(frames)
        feedback.pushInfo('GSD: %.4f m/px (x), %.4f m/px (y)' % (px, py))
        feedback.pushInfo('Frame: %d x %d px | step: %d x %d px | grid up to %d frame(s)'
                          % (fw, fh, step_x, step_y, total))

        manifest_path = os.path.join(out_dir, 'frames.csv')
        written = 0
        with open(manifest_path, 'w', newline='', encoding='utf-8') as mf:
            writer = csv.writer(mf)
            writer.writerow(['frame', 'filename', 'row', 'col',
                             'center_x', 'center_y',
                             'min_x', 'min_y', 'max_x', 'max_y',
                             'width_px', 'height_px'])
            for (ri, ci, xoff, yoff) in frames:
                if feedback.isCanceled():
                    break
                xsize, ysize = fw, fh
                if xoff + xsize > W or yoff + ysize > H:
                    if not keep_partial:
                        continue
                    xsize = min(xsize, W - xoff)
                    ysize = min(ysize, H - yoff)

                written += 1
                name = 'frame_%04d.jpg' % written
                dst = os.path.join(out_dir, name)
                out_ds = gdal.Translate(
                    dst, ds,
                    srcWin=[xoff, yoff, xsize, ysize],
                    format='JPEG',
                    bandList=band_list,
                    creationOptions=['QUALITY=%d' % quality, 'WORLDFILE=YES'],
                )
                if out_ds is None:
                    raise QgsProcessingException(
                        self.tr('GDAL failed to write %s' % name))
                out_ds = None

                min_x = gt[0] + xoff * gt[1]
                max_x = gt[0] + (xoff + xsize) * gt[1]
                max_y = gt[3] + yoff * gt[5]
                min_y = gt[3] + (yoff + ysize) * gt[5]
                writer.writerow([
                    written, name, ri, ci,
                    '%.3f' % ((min_x + max_x) / 2.0),
                    '%.3f' % ((min_y + max_y) / 2.0),
                    '%.3f' % min_x, '%.3f' % min_y,
                    '%.3f' % max_x, '%.3f' % max_y,
                    xsize, ysize,
                ])
                if total:
                    feedback.setProgress(int(100 * written / total))

        ds = None
        if written == 0 and not feedback.isCanceled():
            raise QgsProcessingException(self.tr(
                'No complete frame fits — the frame footprint is larger than the '
                'raster. Reduce the frame size or enable "Keep partial edge frames".'))

        feedback.pushInfo('Wrote %d frame(s) to %s' % (written, out_dir))
        return {self.OUTPUT: out_dir, 'FRAME_COUNT': written, 'MANIFEST': manifest_path}

    def name(self):
        return 'simulate_drone_frames'

    def displayName(self):
        return self.tr('Simulate drone frames from raster')

    def group(self):
        return self.tr('Drone Tiler')

    def groupId(self):
        return 'dronetiler'

    def shortHelpString(self):
        return self.tr(
            'Slices a north-up GeoTIFF into overlapping JPEG frames that mimic a '
            'UAV/drone photo survey laid out in a lawnmower grid.\n\n'
            'Frame size is a ground footprint in metres; forward and side overlap set '
            'the spacing. Each frame is written with a world file (.wld) so the tiles '
            'drop back into QGIS in place, plus a frames.csv manifest of centres and '
            'bounds.\n\n'
            'Requirements: north-up, georeferenced, 8-bit (Byte) raster.')

    def createInstance(self):
        return DroneTilerAlgorithm()

    def tr(self, text):
        return QCoreApplication.translate('DroneTilerAlgorithm', text)
