# -*- coding: utf-8 -*-
"""Plugin entry point: registers the Drone Tiler processing provider."""
from qgis.core import QgsApplication

from .provider import DroneTilerProvider


class DroneTilerPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.provider = None

    def initProcessing(self):
        self.provider = DroneTilerProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
