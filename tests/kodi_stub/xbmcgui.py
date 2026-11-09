"""Minimal xbmcgui stub used by the offline test harness."""

import xbmc

NOTIFICATION_INFO = 'info'
NOTIFICATION_WARNING = 'warning'
NOTIFICATION_ERROR = 'error'


class ListItem(object):
    def __init__(self, label='', path='', offscreen=False):
        self.label = label
        self.path = path
        self.properties = {}
        self.art = {}
        self.info = {}
        self.mime = None
        self.content_lookup = True

    def setProperty(self, key, value):
        self.properties[key] = value

    def getProperty(self, key):
        return self.properties.get(key)

    def setArt(self, art):
        self.art.update(art or {})

    def setInfo(self, info_type, info):
        self.info.update(info or {})

    def setMimeType(self, mime):
        self.mime = mime

    def setContentLookup(self, value):
        self.content_lookup = value

    def setPath(self, path):
        self.path = path

    def setLabel(self, label):
        self.label = label

    def setPlaying(self, value):
        pass


class Dialog(object):
    def notification(self, heading, message, icon=NOTIFICATION_INFO, time=5000, sound=True):
        xbmc.NOTIFICATIONS.append((heading, message, icon))

    def select(self, heading, options, autoclose=0, preselect=-1, useDetails=False):
        return -1

    def input(self, heading, defaultt='', type=0, option=0, autoclose=0):
        return xbmc.KEYBOARD_TEXT

    def ok(self, heading, message):
        return True
