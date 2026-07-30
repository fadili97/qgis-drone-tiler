# -*- coding: utf-8 -*-
"""Slice a north-up GeoTIFF into overlapping JPEG frames that mimic a
UAV/drone photo survey (lawnmower grid)."""
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFolderDestination,
)

from .core import tile_raster, TilerError


class DroneTilerAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    FRAME_W = 'FRAME_W'
    FRAME_H = 'FRAME_H'
    FWD_OVERLAP = 'FWD_OVERLAP'
    SIDE_OVERLAP = 'SIDE_OVERLAP'
    SERPENTINE = 'SERPENTINE'
    KEEP_PARTIAL = 'KEEP_PARTIAL'
    QUALITY = 'QUALITY'
    OUT_W = 'OUT_W'
    OUT_H = 'OUT_H'
    RESAMPLE = 'RESAMPLE'
    OUTPUT = 'OUTPUT'

    RESAMPLE_METHODS = ['cubic', 'lanczos', 'bilinear', 'nearest']

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
        self.addParameter(QgsProcessingParameterNumber(
            self.OUT_W, self.tr('Output frame width in px (0 = native crop)'),
            QgsProcessingParameterNumber.Integer, 0, minValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.OUT_H, self.tr('Output frame height in px (0 = native crop)'),
            QgsProcessingParameterNumber.Integer, 0, minValue=0))
        self.addParameter(QgsProcessingParameterEnum(
            self.RESAMPLE, self.tr('Resampling (only used when resizing)'),
            options=self.RESAMPLE_METHODS, defaultValue=0))
        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUTPUT, self.tr('Output folder')))

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        if layer is None:
            raise QgsProcessingException(self.tr('Invalid input raster.'))
        out_dir = self.parameterAsString(parameters, self.OUTPUT, context)

        try:
            result = tile_raster(
                layer.source(), out_dir,
                frame_w_m=self.parameterAsDouble(parameters, self.FRAME_W, context),
                frame_h_m=self.parameterAsDouble(parameters, self.FRAME_H, context),
                fwd_overlap=self.parameterAsDouble(parameters, self.FWD_OVERLAP, context),
                side_overlap=self.parameterAsDouble(parameters, self.SIDE_OVERLAP, context),
                serpentine=self.parameterAsBool(parameters, self.SERPENTINE, context),
                keep_partial=self.parameterAsBool(parameters, self.KEEP_PARTIAL, context),
                quality=self.parameterAsInt(parameters, self.QUALITY, context),
                out_w=self.parameterAsInt(parameters, self.OUT_W, context),
                out_h=self.parameterAsInt(parameters, self.OUT_H, context),
                resample=self.RESAMPLE_METHODS[
                    self.parameterAsEnum(parameters, self.RESAMPLE, context)],
                log=feedback.pushInfo,
                progress=feedback.setProgress,
                is_canceled=feedback.isCanceled,
            )
        except TilerError as e:
            raise QgsProcessingException(str(e))

        return {self.OUTPUT: out_dir,
                'FRAME_COUNT': result['count'],
                'MANIFEST': result['manifest']}

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
