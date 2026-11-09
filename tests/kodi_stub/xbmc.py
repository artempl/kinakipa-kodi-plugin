"""Minimal xbmc stub used by the offline test harness."""

LOGDEBUG = 0
LOGINFO = 1
LOGWARNING = 2
LOGERROR = 3
LOGFATAL = 4

LOGS = []
BUILTINS = []
COND = {}
SETTINGS = {}
ITEMS = []
CONTENT = None
RESOLVED = None
ENDED = None
NOTIFICATIONS = []
ADDON_PATH = ''
PROFILE = ''
KEYBOARD_TEXT = ''


def reset():
    LOGS.clear()
    BUILTINS.clear()
    ITEMS.clear()
    COND.clear()
    NOTIFICATIONS.clear()
    global CONTENT, RESOLVED, ENDED, KEYBOARD_TEXT
    CONTENT = None
    RESOLVED = None
    ENDED = None
    KEYBOARD_TEXT = ''


def log(message, level=LOGDEBUG):
    LOGS.append((level, message))


def executebuiltin(command, wait=False):
    BUILTINS.append(command)


def getCondVisibility(condition):
    return COND.get(condition, False)


def getInfoLabel(label):
    return ''


class Keyboard(object):
    def __init__(self, default='', heading='', hidden=False):
        self._text = default

    def doModal(self, autoclose=0):
        pass

    def isConfirmed(self):
        return bool(self._text)

    def getText(self):
        return self._text

    def setText(self, text):
        self._text = text
