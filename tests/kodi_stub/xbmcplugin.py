"""Minimal xbmcplugin stub used by the offline test harness."""

import xbmc


def addDirectoryItem(handle, url, listitem, isFolder=False, totalItems=0):
    xbmc.ITEMS.append({
        'url': url,
        'label': listitem.label,
        'folder': isFolder,
        'item': listitem,
    })
    return True


def addDirectoryItems(handle, items, totalItems=0):
    for url, listitem, isFolder in items:
        addDirectoryItem(handle, url, listitem, isFolder)
    return True


def endOfDirectory(handle, succeeded=True, updateListing=False, cacheToDisc=True):
    xbmc.ENDED = succeeded


def setContent(handle, content):
    xbmc.CONTENT = content


def setResolvedUrl(handle, succeeded, listitem):
    xbmc.RESOLVED = {
        'ok': succeeded,
        'path': getattr(listitem, 'path', None),
        'item': listitem,
    }


def addSortMethod(handle, sortMethod, label2Mask=''):
    pass


def setPluginCategory(handle, category):
    pass


def setPluginFanart(handle, image, color1='', color2='', color3=''):
    pass
