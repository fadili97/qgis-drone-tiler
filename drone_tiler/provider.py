# -*- coding: utf-8 -*-
from qgis.core import QgsProcessingProvider

from .algorithm import DroneTilerAlgorithm


class DroneTilerProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        self.addAlgorithm(DroneTilerAlgorithm())

    def id(self):
        return 'dronetiler'

    def name(self):
        return 'Drone Tiler'

    def longName(self):
        return 'Drone Tiler — simulate UAV frames from a raster'
