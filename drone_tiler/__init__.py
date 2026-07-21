# -*- coding: utf-8 -*-
def classFactory(iface):
    from .drone_tiler_plugin import DroneTilerPlugin
    return DroneTilerPlugin(iface)
