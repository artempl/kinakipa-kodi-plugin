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
    movie = harness.run('item', id='326')
    CHECKER.check(len(movie.items) >= 1, 'movie sources listed', str(len(movie.items)))
    CHECKER.check(all(i['item'].properties.get('IsPlayable') for i in movie.items),
                  'movie sources are playable')
    CHECKER.check(not movie.notifications, 'movie view has no errors', repr(movie.notifications))

    print('== series item (77044) ==')
    series = harness.run('item', id='77044')
    CHECKER.check(len(series.items) >= 20, 'series episodes listed', str(len(series.items)))
    if series.items:
        CHECKER.check(series.items[0]['label'].startswith('С1Э1'),
                      'episode label format', series.items[0]['label'])

    print('== multi-season series (10250911) ==')
    kevin = harness.run('item', id='10250911')
    CHECKER.check(len(kevin.items) == 8, 'kevin has 8 episodes', str(len(kevin.items)))

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

        mp4 = harness.run('play', settings={'playback_mode': '2'},
                          u=play_params.get('u'), t='test', p='')
        CHECKER.check(mp4.resolved and mp4.resolved['ok'], 'MP4 resolves',
                      repr(mp4.notifications))
        if mp4.resolved and mp4.resolved['ok']:
            CHECKER.check('.mp4' in mp4.resolved['path'], 'MP4 path is progressive',
                          mp4.resolved['path'])

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
