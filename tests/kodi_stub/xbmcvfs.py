"""Minimal xbmcvfs stub used by the offline test harness."""


def translatePath(path):
    return path


def exists(path):
    import os
    return os.path.exists(path)


def mkdir(path):
    import os
    try:
        os.makedirs(path)
        return True
    except OSError:
        return False
