#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run plugin.video.kinakipa without Kodi (xbmc stubs) against the live site."""

import runpy
import os
import shutil
import sys
import tempfile
import traceback
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ADDON_DIR = os.path.join(ROOT, 'plugin.video.kinakipa')
STUB_DIR = os.path.join(HERE, 'kodi_stub')
MAIN_PY = os.path.join(ADDON_DIR, 'main.py')

sys.path.insert(0, STUB_DIR)

import xbmc  # noqa: E402
import xbmcgui  # noqa: E402

PROFILE = tempfile.mkdtemp(prefix='kinakipa-test-')
_MODULE_COUNTER = [0]


class Result(object):
    def __init__(self):
        self.items = []
        self.notifications = []
        self.resolved = None
        self.builtins = []
        self.content = None
        self.ended = None

    def __repr__(self):
        return '<Result %d items, resolved=%r>' % (len(self.items), self.resolved)


def run(action='root', settings=None, has_inputstream=True, **params):
    """Execute one plugin invocation and capture what it produced."""
    xbmc.reset()
    xbmc.SETTINGS.clear()
    xbmc.SETTINGS.update({
        'base_url': 'https://kinakipa.site',
        'page_size': '1',
        'playback_mode': '2',
        'mp4_quality': '1',
        'cookie': '',
        'user_agent': '',
    })
    if settings:
        xbmc.SETTINGS.update(settings)

    xbmc.ADDON_PATH = ADDON_DIR
    xbmc.PROFILE = PROFILE
    xbmc.COND['System.HasAddon(inputstream.adaptive)'] = bool(has_inputstream)

    query = {'action': action}
    query.update({k: v for k, v in params.items() if v is not None})
    sys.argv = ['plugin://plugin.video.kinakipa/', '1',
                '?' + urllib.parse.urlencode(query)]

    _MODULE_COUNTER[0] += 1
    runpy.run_path(MAIN_PY, run_name='__main__')

    result = Result()
    result.items = list(xbmc.ITEMS)
    result.notifications = list(xbmc.NOTIFICATIONS)
    result.resolved = xbmc.RESOLVED
    result.builtins = list(xbmc.BUILTINS)
    result.content = xbmc.CONTENT
    result.ended = xbmc.ENDED
    return result


def cleanup():
    shutil.rmtree(PROFILE, ignore_errors=True)


class Checker(object):
    def __init__(self):
        self.failures = []
        self.passes = 0

    def check(self, condition, label, detail=''):
        if condition:
            self.passes += 1
            print('  ok   %s' % label)
        else:
            self.failures.append((label, detail))
            print('  FAIL %s %s' % (label, detail))

    def summary(self):
        print('\n%d checks passed, %d failed' % (self.passes, len(self.failures)))
        for label, detail in self.failures:
            print('  - %s %s' % (label, detail))
        return 0 if not self.failures else 1


def guarded(checker, label, func):
    try:
        return func()
    except Exception as exc:  # noqa: BLE001
        checker.check(False, label, 'exception: %s' % exc)
        traceback.print_exc()
        return None
