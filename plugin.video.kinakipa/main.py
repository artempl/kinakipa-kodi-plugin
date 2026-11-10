#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Кінакіпа — Kodi video add-on.

Browse and stream Belarusian-dubbed movies and TV shows from kinakipa.site.

Entry point for plugin.video.kinakipa (Kodi 19+/21, Python 3, stdlib only).
"""

import html as htmllib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs


PLUGIN_URL = sys.argv[0]
HANDLE = int(sys.argv[1])
# Resolve the add-on explicitly: some Kodi builds do not wire up the calling
# add-on for xbmcaddon.Addon() without an id, which breaks openSettings().
ADDON_ID = (PLUGIN_URL.split('://', 1)[1].split('/', 1)[0]
            if '://' in PLUGIN_URL else 'plugin.video.kinakipa')
ADDON = xbmcaddon.Addon(ADDON_ID)
ADDON_NAME = ADDON.getAddonInfo('name')
PROFILE_DIR = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))

DEFAULT_UA = (
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
)
HTTP_TIMEOUT = 25
CACHE_TTL = 7 * 24 * 3600        # resolved stream URLs live long enough
FILTERS_TTL = 3 * 24 * 3600      # genre/country lists


# ---------------------------------------------------------------------------
# Settings and logging
# ---------------------------------------------------------------------------

CONFIG_FILE = 'config.json'
_CONFIG = None


def config():
    """User settings live in the add-on profile (Kodi's own dialog is not
    available for add-ons on every build/skin, so the add-on has its own)."""
    global _CONFIG
    if _CONFIG is None:
        path = os.path.join(PROFILE_DIR, CONFIG_FILE)
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
            _CONFIG = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _CONFIG = {}
    return _CONFIG


def config_set(key, value):
    global _CONFIG
    data = dict(config())
    data[key] = value
    _CONFIG = data
    path = os.path.join(PROFILE_DIR, CONFIG_FILE)
    try:
        if not os.path.isdir(PROFILE_DIR):
            os.makedirs(PROFILE_DIR)
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1)
    except OSError as exc:
        log('cannot save settings: %s' % exc, xbmc.LOGWARNING)


def _setting(key, default=''):
    value = config().get(key)
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if value in (None, ''):
        try:
            value = ADDON.getSetting(key)
        except Exception:
            value = ''
    return value if value not in (None, '') else default


def _int_setting(key, default):
    value = config().get(key)
    if value is None:
        try:
            value = ADDON.getSetting(key)
        except Exception:
            value = ''
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _page_size():
    sizes = (20, 50, 100)
    index = _int_setting('page_size', 1)
    return sizes[index] if 0 <= index < len(sizes) else 50


def _mp4_quality():
    qualities = (1080, 720, 480, 360, 240)
    index = _int_setting('mp4_quality', 1)
    return qualities[index] if 0 <= index < len(qualities) else 720


def _playback_mode():
    return {0: 'auto', 1: 'hls', 2: 'mp4'}.get(_int_setting('playback_mode', 0), 'auto')


def _hls_quality():
    """Fixed HLS rendition height, or None for adaptive playback."""
    heights = (1080, 720, 480, 360, 240)
    index = _int_setting('hls_quality', 0) - 1
    return heights[index] if 0 <= index < len(heights) else None


def log(message, level=xbmc.LOGDEBUG):
    xbmc.log('[kinakipa] %s' % message, level)


def notify(message, heading=None, icon=xbmcgui.NOTIFICATION_INFO, timeout=5000):
    xbmcgui.Dialog().notification(heading or ADDON_NAME, message, icon, timeout)


class SiteError(Exception):
    """Raised when kinakipa.site cannot be reached or parsed."""


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

def _site():
    return _setting('base_url', 'https://kinakipa.site').rstrip('/')


def _request_headers(referer=None):
    headers = {
        'User-Agent': _setting('user_agent', DEFAULT_UA),
        'Accept': 'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8',
        'Accept-Language': 'be-BY,be;q=0.9,ru;q=0.8,en;q=0.6',
    }
    if referer:
        headers['Referer'] = referer
    cookie = _setting('cookie', '').strip()
    if cookie:
        headers['Cookie'] = cookie
    return headers


def http_get(url, referer=None):
    """Fetch *url* and return decoded text."""
    log('GET %s' % url)
    request = urllib.request.Request(url, headers=_request_headers(referer))
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            raw = response.read()
            encoding = (response.headers.get('Content-Encoding') or '').lower()
            if encoding == 'gzip':
                import gzip
                raw = gzip.decompress(raw)
            return raw.decode('utf-8', 'replace')
    except urllib.error.HTTPError as exc:
        raise SiteError('HTTP %s' % exc.code)
    except urllib.error.URLError as exc:
        raise SiteError('Network error: %s' % exc.reason)
    except Exception as exc:  # noqa: BLE001 - surface anything to the UI
        raise SiteError(str(exc))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_location(url):
    """Return the Location header of *url* without following it."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers=_request_headers())
    try:
        opener.open(request, timeout=HTTP_TIMEOUT)
    except urllib.error.HTTPError as exc:
        return exc.headers.get('Location')
    except Exception as exc:  # noqa: BLE001
        raise SiteError(str(exc))
    return None


def http_json(url, referer=None):
    text = http_get(url, referer=referer)
    try:
        return json.loads(text)
    except ValueError:
        raise SiteError('Bad JSON response')


def http_exists(url):
    """Cheap existence probe (Bunny CDN answers HEAD)."""
    request = urllib.request.Request(url, method='HEAD',
                                     headers=_request_headers())
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return 200 <= response.status < 300
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Small cache (stream URLs, filter lists) stored in the add-on profile
# ---------------------------------------------------------------------------

def _cache_file():
    try:
        if not os.path.isdir(PROFILE_DIR):
            os.makedirs(PROFILE_DIR)
        return os.path.join(PROFILE_DIR, 'cache.json')
    except OSError:
        return None


def _cache_load():
    path = _cache_file()
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _cache_store(data):
    path = _cache_file()
    if not path:
        return
    try:
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(data, handle)
    except OSError:
        pass


def cache_get(key, ttl=CACHE_TTL):
    entry = _cache_load().get(key)
    if isinstance(entry, dict) and time.time() - entry.get('ts', 0) < ttl:
        return entry.get('value')
    return None


def cache_set(key, value):
    data = _cache_load()
    data[key] = {'ts': time.time(), 'value': value}
    _cache_store(data)


# ---------------------------------------------------------------------------
# Favourites (stored as JSON in the add-on profile)
# ---------------------------------------------------------------------------

FAVORITES_FILE = 'favorites.json'
_FAVORITES = None


def favorites():
    global _FAVORITES
    if _FAVORITES is not None:
        return _FAVORITES
    path = os.path.join(PROFILE_DIR, FAVORITES_FILE)
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = []
    _FAVORITES = data if isinstance(data, list) else []
    return _FAVORITES


def _save_favorites(items):
    global _FAVORITES
    _FAVORITES = items
    path = os.path.join(PROFILE_DIR, FAVORITES_FILE)
    try:
        if not os.path.isdir(PROFILE_DIR):
            os.makedirs(PROFILE_DIR)
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(items, handle, ensure_ascii=False, indent=1)
    except OSError as exc:
        log('cannot write favourites: %s' % exc, xbmc.LOGWARNING)


def is_favorite(movie_id):
    return any(item.get('id') == str(movie_id) for item in favorites())


def toggle_favorite(entry):
    """Add or remove a title; returns True when it was added."""
    items = list(favorites())
    for index, item in enumerate(items):
        if item.get('id') == entry['id']:
            items.pop(index)
            _save_favorites(items)
            return False
    entry = dict(entry)
    entry['ts'] = time.time()
    items.insert(0, entry)
    _save_favorites(items)
    return True


def _favorite_menu(entry):
    label = 'Выдаліць з фаварытаў' if is_favorite(entry['id']) \
        else 'Дадаць у фаварыты'
    action = 'RunPlugin(%s)' % _url('fav_toggle', id=entry['id'],
                                    t=entry.get('title', ''),
                                    p=entry.get('poster', ''),
                                    y=entry.get('year', ''))
    return [(label, action)]


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _clean(text):
    return re.sub(r'\s+', ' ', text or '').strip()


def _text(fragment):
    return _clean(htmllib.unescape(re.sub(r'<[^>]+>', ' ', fragment or '')))


def _attr(fragment, name):
    match = re.search(r'%s="([^"]*)"' % re.escape(name), fragment or '')
    return htmllib.unescape(match.group(1)) if match else ''


def _split_list(value):
    parts = re.split(r'\s*(?:,| і )\s*', value or '')
    return [_clean(part) for part in parts if _clean(part)]


# ---------------------------------------------------------------------------
# Site parsers
# ---------------------------------------------------------------------------

CARD_RE = re.compile(r'<a\s+[^>]*href="/movie\?id=(\d+)"[^>]*>', re.I)

SORTING_LABELS = {
    'kinopoisk-rating-up': 'Рэйтынг КП ⬆',
    'imdb-rating-up': 'Рэйтынг IMDb ⬆',
    'kinopoisk-vote-up': 'Галасы КП ⬆',
    'year-up': 'Год ⬆',
    'premiere-up': "Прэм'ера ⬆",
    'last-modified': 'Дата рэдагавання ⬆',
}


def parse_cards(page):
    """Parse catalog/poster cards out of a listing page."""
    anchors = list(CARD_RE.finditer(page))
    items = []
    for index, match in enumerate(anchors):
        end = anchors[index + 1].start() if index + 1 < len(anchors) else len(page)
        chunk = page[match.end():end]

        poster_match = (re.search(r'<img[^>]*class="poster"[^>]*src="([^"]+)"', chunk)
                        or re.search(r'<img[^>]*src="([^"]+)"[^>]*class="poster"', chunk))
        poster = htmllib.unescape(poster_match.group(1)) if poster_match else ''

        title_match = re.search(r'catalog-item__title">(.*?)</div>', chunk, re.S)
        raw_lines = []
        if title_match:
            raw_lines = [_clean(htmllib.unescape(re.sub(r'<[^>]+>', ' ', line)))
                         for line in re.split(r'[\r\n]+', title_match.group(1))]
            raw_lines = [line for line in raw_lines if line]

        anchor_tag = page[match.start():match.end()]
        title = _attr(anchor_tag, 'title')
        year = ''
        badge = ''
        if raw_lines:
            year_match = re.search(r'((?:19|20)\d{2})(?:\s*[-–]\s*((?:19|20)\d{2}))?\s*$',
                                   raw_lines[0])
            if year_match:
                year = year_match.group(1)
                if year_match.group(2):
                    year = '%s-%s' % (year, year_match.group(2))
                rest = raw_lines[0][:year_match.start()].strip()
                if rest:
                    title = rest
            if len(raw_lines) > 1:
                badge = ' '.join(raw_lines[1:])

        if not title:
            title = raw_lines[0] if raw_lines else 'Без назвы'

        items.append({
            'id': match.group(1),
            'title': title,
            'year': year,
            'poster': poster,
            'badge': badge,
        })
    return items


def parse_select(page, select_id):
    """Return [(value, label)] for a <select id="..."> filter."""
    match = re.search(r'<select id="%s".*?</select>' % re.escape(select_id), page, re.S)
    if not match:
        return []
    options = re.findall(r'<option\s+value="([^"]*)"[^>]*>(.*?)</option>',
                         match.group(0), re.S)
    return [(htmllib.unescape(value), _text(label))
            for value, label in options if value.strip()]


def parse_home_sections(page):
    """Split the homepage into titled poster sections."""
    starts = [m.start() for m in re.finditer(r'class="last-episodes-day__title"', page)]
    sections = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(page)
        block = page[start:end]
        title_match = re.search(r'last-episodes-day__title"[^>]*>\s*<span>(.*?)</span>',
                                block, re.S)
        title = _text(title_match.group(1)) if title_match else ''
        cards = parse_cards(block)
        if title and cards:
            sections.append({'title': title, 'items': cards})
    return sections


def parse_item_page(page):
    """Extract metadata from a /movie?id=... page."""
    meta = {
        'type': _attr(page, 'data-cinemaplayer-query-api-type'),
        'title': '', 'original': '', 'year': '', 'poster': '', 'fanart': '',
        'plot': '', 'genres': [], 'countries': [], 'directors': [], 'cast': [],
        'voices': [], 'rating': None, 'votes': '', 'premiere': '', 'age': '',
        'premium': 'прэміум кантэнту' in page.lower(),
    }

    header_match = re.search(r'<h2 class="about-serial-header__title">(.*?)</h2>',
                             page, re.S)
    if header_match:
        header = _text(header_match.group(1))
        year_match = re.search(r'((?:19|20)\d{2})(?:\s*[-–]\s*((?:19|20)\d{2}))?\s*$',
                               header)
        if year_match:
            meta['year'] = year_match.group(1)
            if year_match.group(2):
                meta['year'] = '%s-%s' % (year_match.group(1), year_match.group(2))
            header = header[:year_match.start()]
        meta['title'] = header.strip().strip('«»').strip()

    subtitle_match = re.search(r'about-serial-header__subtitle">(.*?)</div>', page, re.S)
    if subtitle_match:
        subtitle = _text(subtitle_match.group(1))
        subtitle = re.sub(r'\s*/?\s*міні-плэер\s*$', '', subtitle).strip()
        parts = [part.strip() for part in subtitle.split('/') if part.strip()]
        if len(parts) > 1 and not meta['original']:
            meta['original'] = parts[1]
        if not meta['year']:
            year_match = re.search(r'\(((?:19|20)\d{2})\)', subtitle)
            if year_match:
                meta['year'] = year_match.group(1)

    poster_match = re.search(r'<div class="about-serial-poster">\s*<img[^>]+src="([^"]+)"',
                             page)
    if poster_match:
        meta['poster'] = htmllib.unescape(poster_match.group(1))

    fanart_match = re.search(r'<div class="bg-cover-bg">\s*<img[^>]+src="([^"]+)"', page)
    if fanart_match:
        meta['fanart'] = htmllib.unescape(fanart_match.group(1))

    plot_match = re.search(r'<meta name="description" content="([^"]+)"', page)
    if plot_match:
        meta['plot'] = htmllib.unescape(plot_match.group(1))

    for item_match in re.finditer(
            r'<li[^>]*>\s*<span class="font-light-16">(.*?)</span>\s*'
            r'<span class="font-light-18">(.*?)</span>\s*</li>', page, re.S):
        label = _text(item_match.group(1))
        value = _text(item_match.group(2))
        if not label or not value:
            continue
        if label == 'Жанры':
            meta['genres'] = _split_list(value)
        elif label == 'Краіны':
            meta['countries'] = _split_list(value)
        elif label == 'Рэжысёры':
            meta['directors'] = _split_list(value)
        elif label == 'Акцёры':
            meta['cast'] = _split_list(value)
        elif label in ('Пераклад', 'Агучка'):
            meta['voices'].extend(_split_list(value))
        elif label == 'KP':
            rating_match = re.match(r'([\d.,]+)\s*\((\d+)\)', value)
            if rating_match:
                meta['rating'] = float(rating_match.group(1).replace(',', '.'))
                meta['votes'] = rating_match.group(2)
        elif label == "Прэм'ера":
            meta['premiere'] = value
        elif label == 'Узроставы рэйтынг':
            meta['age'] = value

    meta['voices'] = sorted(set(meta['voices']))
    return meta


def fetch_sources(movie_id):
    """Return the playable sources (dubs/episodes) for one title."""
    data = http_json('%s/api/user/player/information?id=%s'
                     % (_site(), urllib.parse.quote(str(movie_id))),
                     referer='%s/movie?id=%s' % (_site(), movie_id))
    if isinstance(data, dict):
        raw = data.get('simple-api') or data.get('simple_api') or []
    elif isinstance(data, list):
        raw = data
    else:
        raw = []

    sources = []
    for source in raw:
        if not isinstance(source, dict):
            continue
        iframe = (source.get('iframe') or '').strip()
        if not iframe:
            continue
        sources.append({
            'name': _clean_dub(source.get('name', ''), iframe),
            'iframe': iframe,
            'season': _to_int(source.get('season')),
            'episode': _to_int(source.get('episode')),
            'supported': _source_supported(iframe),
        })
    return sources


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _source_supported(iframe):
    """True when the iframe can be converted into a stream we can play."""
    lowered = iframe.lower()
    if 'mediadelivery.net/embed/' in lowered:
        return True
    path = lowered.split('?', 1)[0]
    return path.endswith(('.m3u8', '.mp4'))


HOST_SUFFIXES = (
    ('mediadelivery.net', 'BX', ''),
    ('anibel.net', 'A', ' (AniBel)'),
    ('vk.com', 'V', ' (VK)'),
    ('drive.google', 'GX', ' (Google Drive)'),
)


def _clean_dub(name, iframe):
    """Drop the provider code from a source name and tag exotic players."""
    name = _clean(name)
    lowered = (iframe or '').lower()
    for marker, code, suffix in HOST_SUFFIXES:
        if marker in lowered:
            name = re.sub(r'\s*Player\s+%s\s*$' % code, '', name, flags=re.I)
            name = re.sub(r'\s+%s\s*$' % code, '', name, flags=re.I)
            name = name.strip() or 'Крыніца'
            return (name + suffix).strip()
    name = re.sub(r'\s+Player\s+[A-Za-z0-9]+\s*$', '', name)
    return name.strip() or 'Крыніца'


# ---------------------------------------------------------------------------
# Stream resolution
# ---------------------------------------------------------------------------

def _has_inputstream():
    return xbmc.getCondVisibility('System.HasAddon(inputstream.adaptive)')


def resolve_stream(iframe_url):
    """Turn a player iframe URL into a direct stream URL.

    Returns (url, kind) where kind is 'hls' or 'mp4'.
    """
    if 'mediadelivery.net/embed/' in iframe_url:
        playlist = _bunny_playlist(iframe_url)
        mode = _playback_mode()
        # Never hand HLS to a player that cannot decode it.
        if mode == 'mp4' or not _has_inputstream():
            mp4 = _bunny_mp4(playlist)
            if mp4:
                return mp4, 'mp4'
            log('MP4 unavailable, falling back to HLS', xbmc.LOGWARNING)
        quality = _hls_quality()
        if quality:
            try:
                return _pin_quality(playlist, quality) or playlist, 'hls'
            except SiteError as exc:
                log('quality pinning failed: %s' % exc, xbmc.LOGWARNING)
        return playlist, 'hls'

    lowered = iframe_url.lower()
    if '.m3u8' in lowered:
        return iframe_url, 'hls'
    if '.mp4' in lowered:
        return iframe_url, 'mp4'

    if 'video.anibel.net' in lowered:
        raise SiteError('крыніца AniBel патрабуе ўваходу праз сайт')

    page = http_get(iframe_url, referer=_site() + '/')
    for pattern, kind in ((r'https?://[^"\'\s]+?\.m3u8[^"\'\s]*', 'hls'),
                          (r'https?://[^"\'\s]+?\.mp4[^"\'\s]*', 'mp4')):
        match = re.search(pattern, page)
        if match:
            return htmllib.unescape(match.group(0)), kind
    raise SiteError('крыніца не падтрымліваецца')


def _bunny_playlist(embed_url):
    """Resolve a Bunny Stream embed page to its HLS playlist URL."""
    match = re.search(r'/embed/([^/?#]+)/([^/?#]+)', embed_url)
    if not match:
        raise SiteError('некарэктная спасылка Bunny')
    cache_key = 'bunny:%s/%s' % (match.group(1), match.group(2))

    cached = cache_get(cache_key)
    if cached:
        return cached

    page = http_get(embed_url, referer=_site() + '/')
    playlist_match = re.search(r'https?://[^"\'\s\\]+?/playlist\.m3u8', page)
    if not playlist_match:
        raise SiteError('не ўдалося знайсці плэйліст Bunny')
    playlist = htmllib.unescape(playlist_match.group(0))
    cache_set(cache_key, playlist)
    return playlist


VARIANT_RE = re.compile(
    r'#EXT-X-STREAM-INF:[^\n]*RESOLUTION=(\d+)x(\d+)[^\n]*\n([^\n#]+)')


def _pin_quality(master_url, height):
    """Return the media playlist of the rendition closest to *height*.

    Pinning a single rendition (instead of handing the master playlist to
    inputstream.adaptive) keeps the quality fixed for the whole playback.
    """
    cache_key = 'variant:%s@%d' % (master_url, height)
    cached = cache_get(cache_key)
    if cached:
        return cached

    text = http_get(master_url)
    variants = []
    for match in VARIANT_RE.finditer(text):
        variant_height = int(match.group(2))
        uri = match.group(3).strip()
        variants.append((variant_height,
                         urllib.parse.urljoin(master_url, uri)))
    if not variants:
        return None
    variants.sort()

    chosen = variants[0]
    for candidate in variants:
        if candidate[0] <= height:
            chosen = candidate
    log('pinned %dp rendition (%dp available)' % (height, chosen[0]))
    cache_set(cache_key, chosen[1])
    return chosen[1]


def _bunny_mp4(playlist_url):
    """Pick the best progressive MP4 rendition for a Bunny playlist."""
    cache_key = 'mp4:%s' % playlist_url
    cached = cache_get(cache_key)
    if cached is not None:
        return cached or None

    base = playlist_url.rsplit('/playlist.m3u8', 1)[0]
    preferred = _mp4_quality()
    qualities = [preferred] + [q for q in (1080, 720, 480, 360, 240) if q != preferred]
    for quality in qualities:
        candidate = '%s/play_%dp.mp4' % (base, quality)
        if http_exists(candidate):
            cache_set(cache_key, candidate)
            return candidate
    cache_set(cache_key, '')
    return None


# ---------------------------------------------------------------------------
# Plugin URL helpers
# ---------------------------------------------------------------------------

def _url(action, _params=None, **params):
    data = dict(_params or {})
    data.update(params)
    data['action'] = action
    clean = {key: str(value) for key, value in data.items()
             if value not in (None, '')}
    return PLUGIN_URL + '?' + urllib.parse.urlencode(clean)


def _add_folder(label, url, art=None, info=None):
    item = xbmcgui.ListItem(label=label)
    if art:
        item.setArt(art)
    if info:
        item.setInfo('video', info)
    xbmcplugin.addDirectoryItem(HANDLE, url, item, True)
    return item


def _add_playable(label, url, art=None, info=None):
    item = xbmcgui.ListItem(label=label)
    item.setProperty('IsPlayable', 'true')
    if art:
        item.setArt(art)
    if info:
        item.setInfo('video', info)
    xbmcplugin.addDirectoryItem(HANDLE, url, item, False)
    return item


def _finish():
    xbmcplugin.endOfDirectory(HANDLE)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def view_root(_params):
    xbmcplugin.setContent(HANDLE, 'files')
    _add_folder('Пошук', _url('search'))
    favourites = favorites()
    _add_folder('Фаварыты (%d)' % len(favourites), _url('favorites'))
    _add_folder('Новыя эпізоды', _url('sec', n='Новыя эпізоды'))
    _add_folder('Актуальныя рэлізы', _url('sec', n='Актуальныя рэлізы'))
    _add_folder('Фільмы', _url('catalog', type='movie', title='Фільмы'))
    _add_folder('Серыялы', _url('catalog', type='tv', title='Серыялы'))
    _add_folder('Мультфільмы', _url('catalog', genre='Мультфільм', title='Мультфільмы'))
    _add_folder('Жанры', _url('genres'))
    _add_folder('Краіны', _url('countries'))
    _add_folder('Гады', _url('years'))
    _add_folder('Усе раздзелы галоўнай', _url('sections'))
    _add_folder('Выпадковы тайтл', _url('random'))
    _add_folder('Налады', _url('settings'))
    _finish()


QUALITY_CHOICES = ('1080p', '720p', '480p', '360p', '240p')

SETTINGS_MENU = (
    ('hls_quality', 'Якасць HLS', ('Адаптыўна (аўта)',) + QUALITY_CHOICES, 0),
    ('playback_mode', 'Спосаб прайгравання',
     ('Аўтаматычна', 'HLS (inputstream.adaptive)', 'MP4'), 0),
    ('mp4_quality', 'Якасць MP4', QUALITY_CHOICES, 1),
    ('page_size', 'Элементаў на старонцы', ('20', '50', '100'), 1),
)


def _setting_value(key, default):
    return _int_setting(key, default)


def view_settings(_params):
    xbmcplugin.setContent(HANDLE, 'files')
    for key, label, choices, default in SETTINGS_MENU:
        current = choices[min(_setting_value(key, default), len(choices) - 1)]
        _add_folder('%s: %s' % (label, current),
                    _url('set_setting', key=key))
    alt = _setting('show_alt_sources') == 'true'
    _add_folder('Крыніцы VK / Google Drive: %s' % ('так' if alt else 'не'),
                _url('toggle_setting', key='show_alt_sources'))
    _add_folder('Скінуць усе налады', _url('set_setting', key='reset'))
    _add_folder('Вярнуцца ў галоўнае меню', _url('root'))
    _finish()


def view_set_setting(params):
    key = params.get('key', '')
    if key == 'reset':
        config_set('hls_quality', 0)
        config_set('playback_mode', 0)
        config_set('mp4_quality', 1)
        config_set('page_size', 1)
        config_set('show_alt_sources', False)
        notify('Налады скінутыя да значэнняў па змаўчанні')
        xbmc.executebuiltin('Container.Refresh')
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    for setting_key, label, choices, default in SETTINGS_MENU:
        if setting_key != key:
            continue
        current = min(_setting_value(key, default), len(choices) - 1)
        index = xbmcgui.Dialog().select(label, list(choices), preselect=current)
        if index >= 0:
            config_set(key, index)
            notify('%s: %s' % (label, choices[index]))
        xbmc.executebuiltin('Container.Refresh')
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    _finish()


def view_toggle_setting(params):
    key = params.get('key', 'show_alt_sources')
    value = _setting(key) != 'true'
    config_set(key, value)
    notify('Крыніцы VK / Google Drive: %s' % ('уключаныя' if value else 'выключаныя'))
    xbmc.executebuiltin('Container.Refresh')
    xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


def view_search(_params):
    keyboard = xbmc.Keyboard('', 'Пошук на Кінакіпа')
    keyboard.doModal()
    if keyboard.isConfirmed():
        query = (keyboard.getText() or '').strip()
        if query:
            view_catalog({'query': query, 'title': 'Пошук: %s' % query})
            return
    xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


def view_favorites(_params):
    xbmcplugin.setContent(HANDLE, 'movies')
    items = favorites()
    if not items:
        notify('Фаварытаў пакуль няма')
        _finish()
        return
    for entry in items:
        label = entry.get('title') or entry.get('id')
        if entry.get('year'):
            label = '%s (%s)' % (label, entry['year'])
        poster = entry.get('poster', '')
        art = {'thumb': poster, 'poster': poster, 'icon': poster}
        item = _add_folder(label, _url('item', id=entry['id']), art=art,
                           info={'title': entry.get('title', ''),
                                 'year': entry.get('year', '')})
        item.addContextMenuItems(_favorite_menu(entry))
    _finish()


def view_favorite_toggle(params):
    movie_id = params.get('id', '')
    if not movie_id:
        _finish()
        return
    added = toggle_favorite({
        'id': movie_id,
        'title': params.get('t', ''),
        'poster': params.get('p', ''),
        'year': params.get('y', ''),
    })
    notify('Дададзена ў фаварыты' if added else 'Выдалена з фаварытаў',
           heading=params.get('t') or ADDON_NAME)
    xbmc.executebuiltin('Container.Refresh')
    xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


def view_sections(_params):
    xbmcplugin.setContent(HANDLE, 'files')
    try:
        sections = parse_home_sections(http_get(_site() + '/'))
    except SiteError as exc:
        notify('Не ўдалося загрузіць галоўную: %s' % exc, icon=xbmcgui.NOTIFICATION_ERROR)
        _finish()
        return
    for section in sections:
        _add_folder('%s (%d)' % (section['title'], len(section['items'])),
                    _url('sec', n=section['title']))
    _finish()


def view_section(params):
    title = params.get('n', '')
    try:
        sections = parse_home_sections(http_get(_site() + '/'))
    except SiteError as exc:
        notify('Не ўдалося загрузіць галоўную: %s' % exc, icon=xbmcgui.NOTIFICATION_ERROR)
        _finish()
        return

    section = next((s for s in sections if s['title'] == title), None)
    if section is None:
        # The homepage rotates sections; fall back to the list of sections.
        for entry in sections:
            _add_folder('%s (%d)' % (entry['title'], len(entry['items'])),
                        _url('sec', n=entry['title']))
        _finish()
        return

    _render_cards(section['items'], 'movies')
    _finish()


def view_genres(_params):
    _render_filter_list('genres', 'genres')


def view_countries(_params):
    _render_filter_list('countries', 'countries')


def _filters():
    cached = cache_get('filters', ttl=FILTERS_TTL)
    if isinstance(cached, dict) and cached.get('genres'):
        return cached
    page = http_get(_site() + '/Catalog')
    data = {
        'genres': parse_select(page, 'genre'),
        'countries': parse_select(page, 'country'),
        'sorting': parse_select(page, 'sorting'),
    }
    if data['genres']:
        cache_set('filters', data)
    return data


def _render_filter_list(kind, action):
    xbmcplugin.setContent(HANDLE, 'files')
    try:
        options = _filters().get(kind) or []
    except SiteError as exc:
        notify('Памылка загрузкі фільтраў: %s' % exc, icon=xbmcgui.NOTIFICATION_ERROR)
        _finish()
        return
    for value, label in options:
        param = 'genre' if kind == 'genres' else 'country'
        _add_folder(label, _url(action, **{param: value, 'title': label}))
    _finish()


def view_years(_params):
    xbmcplugin.setContent(HANDLE, 'files')
    decade = (time.gmtime().tm_year // 10) * 10
    while decade >= 1950:
        label = '%d-%d' % (decade, decade + 9)
        _add_folder(label, _url('catalog', minYear=decade, maxYear=decade + 9,
                                title='Гады: %s' % label))
        decade -= 10
    _add_folder('Да 1949', _url('catalog', minYear=1900, maxYear=1949,
                                title='Гады: да 1949'))
    _finish()


def view_catalog(params):
    page = _to_int(params.get('page')) or 1
    query = {
        'query': params.get('query', ''),
        'type': params.get('type', ''),
        'genre': params.get('genre', ''),
        'country': params.get('country', ''),
        'minYear': params.get('minYear', ''),
        'maxYear': params.get('maxYear', ''),
        'sorting': params.get('sorting', ''),
        'pageSize': _page_size(),
        'pageNumber': page,
    }
    url = _site() + '/Catalog?' + urllib.parse.urlencode(query)
    try:
        page_html = http_get(url)
    except SiteError as exc:
        notify('Памылка загрузкі каталога: %s' % exc, icon=xbmcgui.NOTIFICATION_ERROR)
        _finish()
        return

    heading = params.get('title', 'Каталог')
    xbmcplugin.setContent(HANDLE, 'movies')

    items = parse_cards(page_html)
    if not items:
        notify('Нічога не знойдзена')
        _finish()
        return

    _add_folder('Сартаванне: %s' % _sorting_label(params.get('sorting')),
                _url('sorting', **{k: v for k, v in params.items()
                                   if k not in ('action', 'page', 'sorting')}))

    _render_cards(items, 'movies')

    if 'pagination__next' in page_html:
        next_page = dict(params)
        next_page['page'] = page + 1
        _add_folder('Далей — старонка %d' % (page + 1), _url('catalog', _params=next_page))

    log('catalog %r page %d: %d items' % (heading, page, len(items)))
    _finish()


def _sorting_label(value):
    if not value:
        return 'па змаўчанні'
    return SORTING_LABELS.get(value, value)


def view_sorting(params):
    xbmcplugin.setContent(HANDLE, 'files')
    try:
        options = _filters().get('sorting') or []
    except SiteError as exc:
        notify('Памылка загрузкі: %s' % exc, icon=xbmcgui.NOTIFICATION_ERROR)
        _finish()
        return
    for value, label in options:
        target = dict(params)
        target['sorting'] = value
        _add_folder(label, _url('catalog', _params=target))
    _finish()


def _render_cards(items, content):
    for card in items:
        label = card['title']
        if card['year']:
            label = '%s (%s)' % (label, card['year'])
        if card['badge']:
            label = '%s  [%s]' % (label, card['badge'])
        art = {'thumb': card['poster'], 'poster': card['poster'],
               'icon': card['poster']}
        info = {'title': card['title'], 'year': card['year'],
                'mediatype': 'movie' if content == 'movies' else 'episode'}
        item = _add_folder(label, _url('item', id=card['id']), art=art, info=info)
        item.addContextMenuItems(_favorite_menu({
            'id': card['id'],
            'title': card['title'],
            'poster': card['poster'],
            'year': card['year'],
        }))


def view_item(params):
    movie_id = params.get('id', '')
    season = _to_int(params.get('season'))
    episode = _to_int(params.get('episode'))
    try:
        page_html = http_get('%s/movie?id=%s' % (_site(), urllib.parse.quote(movie_id)))
    except SiteError as exc:
        notify('Памылка загрузкі: %s' % exc, icon=xbmcgui.NOTIFICATION_ERROR)
        _finish()
        return

    meta = parse_item_page(page_html)
    try:
        sources = fetch_sources(movie_id)
    except SiteError as exc:
        log('player info failed: %s' % exc, xbmc.LOGERROR)
        sources = []

    if not sources:
        message = 'Прэміум-кантэнт: патрэбная аўтарызацыя' if meta['premium'] \
            else 'Крыніцы відэа не знойдзеныя'
        notify(message, icon=xbmcgui.NOTIFICATION_WARNING)
        _finish()
        return

    is_tv = meta['type'] == 'tv' or any(s['episode'] for s in sources)
    seasons = sorted({s['season'] for s in sources if s['season']})
    label_prefix = meta['title'] or params.get('title', '')

    art = {'thumb': meta['poster'], 'poster': meta['poster'], 'icon': meta['poster'],
           'fanart': meta['fanart'] or meta['poster']}
    info = _kodi_info(meta, is_tv)

    if season is None:
        favourite_entry = {
            'id': movie_id,
            'title': label_prefix,
            'poster': meta['poster'],
            'year': meta['year'],
        }
        if is_favorite(movie_id):
            _add_folder('У фаварытах — прыбраць',
                        _url('fav_toggle', **_fav_params(favourite_entry)))
        else:
            _add_folder('Дадаць у фаварыты',
                        _url('fav_toggle', **_fav_params(favourite_entry)))

    if is_tv and len(seasons) > 1 and season is None:
        xbmcplugin.setContent(HANDLE, 'seasons')
        for number in seasons:
            count = len({s['episode'] for s in sources
                         if s['season'] == number and s['episode'] is not None})
            label = 'Сезон %d (%d %s)' % (number, count, _episode_word(count))
            season_info = dict(info)
            season_info.update({'season': number,
                                'title': '%s — сезон %d' % (label_prefix, number)})
            _add_folder(label, _url('item', id=movie_id, season=number, title=label_prefix),
                        art=art, info=season_info)
        _finish()
        return

    if season is not None:
        sources = [s for s in sources if s['season'] == season]
    if episode is not None:
        sources = [s for s in sources if s['episode'] == episode]

    xbmcplugin.setContent(HANDLE, 'episodes' if is_tv else 'movies')

    visible = [s for s in sources if s['supported']]
    if _setting('show_alt_sources') == 'true':
        visible = sources
    if not visible:
        # Nothing we can play natively — still show the sources so the user
        # can try (they may work through other add-ons/browsers).
        visible = sources

    def playable(source, label):
        if not source['supported']:
            label = '⚠ %s' % label
        play_url = _url('play', u=source['iframe'],
                        t='%s — %s' % (label_prefix, label), p=meta['poster'])
        item_info = dict(info)
        item_info['title'] = '%s — %s' % (label_prefix, label)
        if source['season']:
            item_info['season'] = source['season']
        if source['episode']:
            item_info['episode'] = source['episode']
        _add_playable(label, play_url, art=art, info=item_info)

    # Dub / subtitles variants of one episode belong together: a single
    # variant stays a playable item, several become one folder.
    if is_tv and episode is None:
        groups, order, flat = {}, [], []
        for source in visible:
            if source['episode'] is None:
                flat.append(source)
                continue
            if source['episode'] not in groups:
                groups[source['episode']] = []
                order.append(source['episode'])
            groups[source['episode']].append(source)

        for number in order:
            group = groups[number]
            if len(group) == 1:
                playable(group[0], _source_label(group[0], True, season))
                continue
            names = ' / '.join(source['name'] for source in group)
            shown_season = group[0]['season'] or season or 1
            label = 'С%dЭ%d · %s' % (shown_season, number, names)
            episode_info = dict(info)
            episode_info.update({'title': '%s — С%dЭ%d' % (label_prefix, shown_season, number),
                                 'season': shown_season,
                                 'episode': number})
            _add_folder(label, _url('item', id=movie_id, season=season,
                                    episode=number, title=label_prefix),
                        art=art, info=episode_info)

        for source in flat:
            playable(source, _source_label(source, True, season))
        _finish()
        return

    for source in visible:
        label = source['name'] if episode is not None \
            else _source_label(source, is_tv, season)
        playable(source, label)
    _finish()


def _episode_word(count):
    if count % 10 == 1 and count % 100 != 11:
        return 'серыя'
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return 'серыі'
    return 'серый'


def _fav_params(entry):
    return {'id': entry['id'], 't': entry.get('title', ''),
            'p': entry.get('poster', ''), 'y': entry.get('year', '')}


def _source_label(source, is_tv, season):
    name = source['name']
    if is_tv and source['episode']:
        number = source['episode']
        if source['season']:
            return 'С%dЭ%d · %s' % (source['season'], number, name)
        return 'Э%d · %s' % (number, name)
    if is_tv and season and not source['episode']:
        return 'С%d · %s' % (season, name)
    return name


def _kodi_info(meta, is_tv):
    info = {
        'title': meta['title'],
        'plot': meta['plot'],
        'year': meta['year'],
        'genre': meta['genres'],
        'country': meta['countries'],
        'director': meta['directors'],
        'cast': meta['cast'],
        'premiered': meta['premiere'],
        'mediatype': 'tvshow' if is_tv else 'movie',
    }
    if meta['rating']:
        info['rating'] = meta['rating']
    if meta['votes']:
        info['votes'] = meta['votes']
    if meta['age']:
        info['mpaa'] = meta['age']
    return {key: value for key, value in info.items() if value not in ('', None, [])}


def view_play(params):
    iframe = params.get('u', '')
    title = params.get('t', '')
    poster = params.get('p', '')
    if not iframe:
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    _play(iframe, title, poster)


def _play(iframe, title, poster):
    try:
        stream, kind = resolve_stream(iframe)
    except SiteError as exc:
        log('resolve failed: %s' % exc, xbmc.LOGERROR)
        notify('Не ўдалося падключыцца да крыніцы: %s' % exc,
               icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return

    log('playing %s (%s)' % (stream, kind))
    item = xbmcgui.ListItem(path=stream)
    if title:
        item.setInfo('video', {'title': title})
    if poster:
        item.setArt({'thumb': poster, 'poster': poster})
    item.setContentLookup(False)

    if kind == 'hls':
        item.setMimeType('application/x-mpegURL')
        if _has_inputstream():
            item.setProperty('inputstream', 'inputstream.adaptive')
            item.setProperty('inputstream.adaptive.manifest_type', 'hls')
    else:
        item.setMimeType('video/mp4')

    xbmcplugin.setResolvedUrl(HANDLE, True, item)


def view_random(_params):
    try:
        location = http_location(_site() + '/api/public/random')
    except SiteError as exc:
        notify('Памылка: %s' % exc, icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    match = re.search(r'id=(\d+)', location or '')
    if not match:
        notify('Не ўдалося выбраць выпадковы тайтл')
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    xbmc.executebuiltin('Container.Update(%s,replace)' % _url('item', id=match.group(1)))
    xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

VIEWS = {
    'root': view_root,
    'search': view_search,
    'favorites': view_favorites,
    'fav_toggle': view_favorite_toggle,
    'sections': view_sections,
    'sec': view_section,
    'genres': view_genres,
    'countries': view_countries,
    'years': view_years,
    'catalog': view_catalog,
    'sorting': view_sorting,
    'item': view_item,
    'play': view_play,
    'random': view_random,
    'settings': view_settings,
    'set_setting': view_set_setting,
    'toggle_setting': view_toggle_setting,
}


def router(paramstring):
    params = dict(urllib.parse.parse_qsl(paramstring))
    action = params.get('action', 'root')
    view = VIEWS.get(action)
    if view is None:
        log('unknown action: %s' % action, xbmc.LOGERROR)
        _finish()
        return
    view(params)


if __name__ == '__main__':
    try:
        raw = sys.argv[2] if len(sys.argv) > 2 else ''
        router(raw[1:] if raw.startswith('?') else raw)
    except SiteError as exc:
        log('site error: %s' % exc, xbmc.LOGERROR)
        notify('Памылка сайта: %s' % exc, icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE)
    except Exception as exc:  # noqa: BLE001 - never crash the Kodi UI
        import traceback
        log('unhandled error: %s' % exc, xbmc.LOGERROR)
        log(traceback.format_exc(), xbmc.LOGERROR)
        notify('Памылка: %s' % exc, icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE)
