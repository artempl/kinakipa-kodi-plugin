"""Minimal xbmcaddon stub used by the offline test harness."""

import xbmc

INFO = {
    'id': 'plugin.video.kinakipa',
    'name': 'Кінакіпа',
    'version': '1.0.0',
    'path': '',
    'profile': '',
    'author': 'arciom',
}


class Addon(object):
    def __init__(self, id=None):
        self._id = id or INFO['id']

    def getAddonInfo(self, key):
        if key == 'path':
            return xbmc.ADDON_PATH
        if key == 'profile':
            return xbmc.PROFILE
        return INFO.get(key, '')

    def getSetting(self, key):
        return xbmc.SETTINGS.get(key, '')

    def setSetting(self, key, value):
        xbmc.SETTINGS[key] = value

    def getLocalizedString(self, string_id):
        return str(string_id)

    def openSettings(self):
        xbmc.BUILTINS.append('OpenSettings')
