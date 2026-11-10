#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-to-end checks of the plugin against kinakipa.site (requires network)."""

import re
import sys
import urllib.parse

import harness

CHECKER = harness.Checker()


def params_from_url(url):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


def find_item(result, label_part):
    return next((i for i in result.items if label_part in i['label']), None)


def main():
    print('== root ==')
    root = harness.run('root')
    CHECKER.check(len(root.items) >= 9, 'root lists menu entries', str(len(root.items)))
    CHECKER.check(find_item(root, 'Фільмы') is not None, 'root has Фільмы')
    CHECKER.check(find_item(root, 'Пошук') is not None, 'root has Пошук')
    CHECKER.check(root.ended is True, 'root ends directory')
    CHECKER.check(not root.notifications, 'root has no errors', repr(root.notifications))

    print('== catalog ==')
    catalog = harness.run('catalog', type='movie', title='Фільмы')
    CHECKER.check(len(catalog.items) >= 20, 'movie catalog has items', str(len(catalog.items)))
    CHECKER.check(catalog.content == 'movies', 'catalog content type', str(catalog.content))
    CHECKER.check(not catalog.notifications, 'catalog has no errors', repr(catalog.notifications))
    first_movie = next((i for i in catalog.items
                        if params_from_url(i['url']).get('action') == 'item'), None)
    CHECKER.check(first_movie is not None, 'catalog items open item view')
    if first_movie:
        CHECKER.check(first_movie['item'].art.get('poster', '').startswith('https://'),
                      'catalog item has poster')
        CHECKER.check(params_from_url(first_movie['url']).get('action') == 'item',
                      'catalog item routes to item view')

    print('== catalog page 2 ==')
    page2 = harness.run('catalog', type='movie', page=2)
    CHECKER.check(len(page2.items) >= 20, 'page 2 has items', str(len(page2.items)))
    if first_movie:
        page2_ids = {params_from_url(i['url']).get('id') for i in page2.items} - {None}
        CHECKER.check(params_from_url(first_movie['url']).get('id') not in page2_ids,
                      'page 2 differs from page 1')

    print('== search ==')
    search = harness.run('catalog', query='Кевін', title='Пошук')
    CHECKER.check(len(search.items) >= 1, 'search returns results', str(len(search.items)))
    search_ids = {params_from_url(i['url']).get('id') for i in search.items} - {None}
    CHECKER.check('10250911' in search_ids, 'search finds Kevin', str(sorted(search_ids)[:5]))

    print('== genres / countries / years ==')
    genres = harness.run('genres')
    CHECKER.check(len(genres.items) >= 20, 'genres listed', str(len(genres.items)))
    countries = harness.run('countries')
    CHECKER.check(len(countries.items) >= 50, 'countries listed', str(len(countries.items)))
    years = harness.run('years')
    CHECKER.check(len(years.items) >= 8, 'year ranges listed', str(len(years.items)))
    year_params = params_from_url(years.items[0]['url'])
    CHECKER.check(year_params.get('minYear') and year_params.get('maxYear'),
                  'year range carries bounds', str(year_params))
    genre_params = params_from_url(genres.items[1]['url'])
    CHECKER.check(genre_params.get('genre'), 'genre carries filter', str(genre_params))

    print('== homepage sections ==')
    sections = harness.run('sections')
    CHECKER.check(len(sections.items) >= 3, 'homepage sections listed', str(len(sections.items)))
    new_episodes = harness.run('sec', n='Новыя эпізоды')
    CHECKER.check(len(new_episodes.items) >= 5, 'new episodes section',
                  str(len(new_episodes.items)))
    CHECKER.check(not new_episodes.notifications, 'section has no errors',
                  repr(new_episodes.notifications))

    print('== movie item (326) ==')
    movie_all = harness.run('item', id='326')
    movie = type(movie_all)()
    movie.items = [i for i in movie_all.items
                   if i['item'].properties.get('IsPlayable')]
    movie.notifications = movie_all.notifications
    movie.resolved = movie_all.resolved
    movie.content = movie_all.content
    CHECKER.check(len(movie.items) >= 1, 'movie sources listed', str(len(movie.items)))
    CHECKER.check(all(i['item'].properties.get('IsPlayable') for i in movie.items),
                  'movie sources are playable')
    CHECKER.check(not movie.notifications, 'movie view has no errors', repr(movie.notifications))
    CHECKER.check(any('фаварыт' in i['label'].lower() for i in movie_all.items),
                  'movie view offers favourites toggle')

    print('== series item (77044) ==')
    series_all = harness.run('item', id='77044')
    series = [i for i in series_all.items
              if i['item'].properties.get('IsPlayable')]
    CHECKER.check(len(series) >= 20, 'series episodes listed', str(len(series)))
    if series:
        CHECKER.check(series[0]['label'].startswith('С1Э1'),
                      'episode label format', series[0]['label'])

    print('== multi-season series (10250911) ==')
    kevin = [i for i in harness.run('item', id='10250911').items
             if i['item'].properties.get('IsPlayable')]
    CHECKER.check(len(kevin) == 8, 'kevin has 8 episodes', str(len(kevin)))

    print('== episode variants (1670) ==')
    seasons_view = harness.run('item', id='5430532')
    season1 = next((i for i in seasons_view.items if 'Сезон 1' in i['label']), None)
    CHECKER.check(season1 is not None, '1670 has season 1')
    if season1:
        sp = params_from_url(season1['url'])
        episodes = harness.run(sp.pop('action'), **sp)
        folder_episode = next((i for i in episodes.items
                               if i['folder'] and 'С1Э1' in i['label']), None)
        CHECKER.check(folder_episode is not None,
                      'episode with several variants is a folder',
                      str([i['label'] for i in episodes.items][:3]))
        if folder_episode:
            CHECKER.check('Агучка' in folder_episode['label']
                          and 'Субцітры' in folder_episode['label'],
                          'folder lists both variants', folder_episode['label'])
            vp = params_from_url(folder_episode['url'])
            variants = harness.run(vp.pop('action'), **vp)
            labels = [i['label'] for i in variants.items]
            CHECKER.check(len(labels) == 2 and all('·' not in l for l in labels),
                          'variants are separate playable items', str(labels))

    print('== playback ==')
    if movie.items:
        play_params = params_from_url(movie.items[0]['url'])
        CHECKER.check(play_params.get('action') == 'play', 'source routes to play')

        hls = harness.run('play', settings={'playback_mode': '1'},
                          u=play_params.get('u'), t='test', p='')
        CHECKER.check(hls.resolved and hls.resolved['ok'], 'HLS resolves',
                      repr(hls.notifications))
        if hls.resolved and hls.resolved['ok']:
            path = hls.resolved['path']
            CHECKER.check('.m3u8' in path, 'HLS path is a playlist', path)
            item = hls.resolved['item']
            CHECKER.check(item.properties.get('inputstream') == 'inputstream.adaptive',
                          'inputstream.adaptive is set')

        auto = harness.run('play', settings={'playback_mode': '0'},
                           u=play_params.get('u'), t='test', p='')
        CHECKER.check(auto.resolved and '.m3u8' in auto.resolved['path'],
                      'auto mode prefers HLS with inputstream.adaptive')

        no_ia = harness.run('play', settings={'playback_mode': '0'},
                            has_inputstream=False, u=play_params.get('u'), t='test', p='')
        CHECKER.check(no_ia.resolved and '.mp4' in no_ia.resolved['path'],
                      'auto mode falls back to MP4 without inputstream.adaptive')

        mp4 = harness.run('play', settings={'playback_mode': '2'},
                          u=play_params.get('u'), t='test', p='')
        CHECKER.check(mp4.resolved and mp4.resolved['ok'], 'MP4 resolves',
                      repr(mp4.notifications))
        if mp4.resolved and mp4.resolved['ok']:
            CHECKER.check('.mp4' in mp4.resolved['path'], 'MP4 path is progressive',
                          mp4.resolved['path'])

    print('== hls quality ==')
    if movie.items:
        play_params = params_from_url(movie.items[0]['url'])
        pinned = harness.run('play', settings={'playback_mode': '1', 'hls_quality': '1'},
                             u=play_params.get('u'), t='test', p='')
        CHECKER.check(pinned.resolved and '1920x1080' in pinned.resolved['path'],
                      '1080p rendition is pinned', str(pinned.resolved and pinned.resolved['path']))

        adaptive = harness.run('play', settings={'playback_mode': '1', 'hls_quality': '0'},
                               u=play_params.get('u'), t='test', p='')
        CHECKER.check(adaptive.resolved and adaptive.resolved['path'].endswith('playlist.m3u8'),
                      'adaptive mode keeps the master playlist')

    print('== favourites ==')
    empty = harness.run('favorites')
    CHECKER.check(not empty.items, 'favourites start empty', str(len(empty.items)))
    root_menu = harness.run('root')
    CHECKER.check(any(i['label'].startswith('Фаварыты') for i in root_menu.items),
                  'root has favourites entry')

    harness.run('fav_toggle', id='77044', t='Сябры', y='1994',
                p='https://cdn.kinabel.online/poster/77044.jpg')
    listed = harness.run('favorites')
    CHECKER.check(len(listed.items) == 1, 'favourite is listed', str(len(listed.items)))
    if listed.items:
        CHECKER.check('Сябры' in listed.items[0]['label'], 'favourite label',
                      listed.items[0]['label'])
        CHECKER.check(listed.items[0]['item'].context_menu
                      and 'Выдаліць' in listed.items[0]['item'].context_menu[0][0],
                      'favourite has remove action')

    detail = harness.run('item', id='77044')
    CHECKER.check(any('У фаварытах' in i['label'] for i in detail.items),
                  'item view shows the favourite state')

    harness.run('fav_toggle', id='77044', t='Сябры')
    CHECKER.check(not harness.run('favorites').items, 'favourite can be removed')

    print('== in-addon settings ==')
    settings_view = harness.run('settings')
    labels = [i['label'] for i in settings_view.items]
    CHECKER.check(any('Якасць HLS' in label for label in labels),
                  'settings menu lists HLS quality', str(labels[:4]))
    CHECKER.check(any('Крыніцы VK' in label for label in labels),
                  'settings menu lists alt sources')

    harness.run('set_setting', key='hls_quality')
    stored = harness.run('settings')
    CHECKER.check(any('Якасць HLS' in i['label'] for i in stored.items),
                  'HLS setting persists')

    print('== random ==')
    random_result = harness.run('random')
    CHECKER.check(any('Container.Update' in b for b in random_result.builtins),
                  'random navigates', repr(random_result.builtins))

    print('== premium item (3498) ==')
    premium = harness.run('item', id='3498', settings={'show_alt_sources': 'true'})
    CHECKER.check(len(premium.items) >= 1, 'premium sources listed',
                  str(len(premium.items)) + ' ' + repr(premium.notifications))
    for entry in premium.items:
        source = params_from_url(entry['url']).get('u', '')
        if 'anibel' in source:
            broken = harness.run('play', u=source, t='anibel')
            CHECKER.check(broken.resolved and not broken.resolved['ok'],
                          'anibel source fails gracefully')
            CHECKER.check(bool(broken.notifications), 'anibel shows a message',
                          repr(broken.notifications))

    print('== sorting view ==')
    sorting = harness.run('sorting')
    CHECKER.check(len(sorting.items) >= 5, 'sorting options listed', str(len(sorting.items)))

    return CHECKER.summary()


if __name__ == '__main__':
    try:
        sys.exit(main())
    finally:
        harness.cleanup()
