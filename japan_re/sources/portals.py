"""The three national portals. Between them they carry most agency stock in Kanto.

Search URLs and detail-link patterns were written from the sites' public URL
structure; the first live crawl is what confirms them (a wrong slug shows up as a
404 or an empty target in the crawl log, not as bad data).
"""
from __future__ import annotations

import re
import urllib.parse

from .base import SearchTarget, Source

PREF_SLUG = {'Tokyo': 'tokyo', 'Kanagawa': 'kanagawa'}
PREF_CODE = {'Tokyo': '13', 'Kanagawa': '14'}


class Suumo(Source):
    id = 'suumo'
    name = 'SUUMO (Recruit)'
    base_url = 'https://suumo.jp/'
    kind = 'portal'
    policy = 'personal_use_only'
    policy_notes = ('Terms art. 2(1): no use beyond private use under the Copyright Act without '
                    'consent; art. 3(1)(6)-(7): no interfering with operation, no commercial use. '
                    'robots.txt has 300+ Disallow rules for all agents; enforced per URL.')
    enabled_by_default = True
    # /chukoikkodate/tokyo/sc_musashino/nc_76543210/  /tochi/.../nc_123/  /ms/chuko/.../nc_123/
    detail_re = re.compile(r'suumo\.jp/(?:chukoikkodate|ikkodate|tochi|ms/chuko)/[^?#]*?nc_(?P<id>\d+)/?(?:$|[?#])')

    # SUUMO's search takes the JIS city code directly, so no slug guessing:
    # bs=021 used detached houses, bs=030 land, bs=011 used condos.
    BS = {'detached_house': '021', 'land': '030', 'condominium': '011'}

    def search_targets(self, munis, categories=('detached_house', 'land')):
        out = []
        for m in munis:
            for cat in categories:
                q = urllib.parse.urlencode({'ar': '030', 'bs': self.BS[cat], 'ta': PREF_CODE[m.pref],
                                            'sc': m.code, 'pc': '100', 'po': '0'})
                out.append(SearchTarget(f'https://suumo.jp/jj/bukken/ichiran/JJ012FC001/?{q}',
                                        cat, f'{m.name_en} / {cat}'))
        return out

    def canonical_url(self, url):
        url = super().canonical_url(url).split('?')[0]
        m = re.search(r'^(.*?nc_\d+/)', url)
        return m.group(1) if m else url

    def extra_pages(self, url):
        return [url.rstrip('/') + '/bukkengaiyo/']   # the full specification tab

    def category_from_url(self, url, default):
        if '/tochi/' in url:
            return 'land'
        if '/ms/' in url:
            return 'condominium'
        if 'ikkodate' in url:
            return 'detached_house'
        return default


class Athome(Source):
    id = 'athome'
    name = "at home"
    base_url = 'https://www.athome.co.jp/'
    kind = 'portal'
    policy = 'unverified'
    policy_notes = ('robots.txt has no group for generic agents (only named bots), so it does not '
                    'restrict us. The terms page (/help/kiyaku.html) refused automated reading '
                    '(HTTP 405), so its terms have not been checked. Read them before enabling.')
    detail_re = re.compile(r'athome\.co\.jp/(?:kodate|tochi|mansion)/(?P<id>\d{8,})/?(?:$|[?#])')
    PATHS = {'detached_house': 'kodate/chuko', 'land': 'tochi', 'condominium': 'mansion/chuko'}

    def search_targets(self, munis, categories=('detached_house', 'land')):
        return [SearchTarget(f'https://www.athome.co.jp/{self.PATHS[c]}/{PREF_SLUG[m.pref]}/{m.slug}/list/',
                             c, f'{m.name_en} / {c}')
                for m in munis for c in categories]

    def category_from_url(self, url, default):
        return {'kodate': 'detached_house', 'tochi': 'land', 'mansion': 'condominium'}.get(
            urllib.parse.urlsplit(url).path.split('/')[1], default)


class Homes(Source):
    id = 'homes'
    name = "LIFULL HOME'S"
    base_url = 'https://www.homes.co.jp/'
    kind = 'portal'
    policy = 'restricted'
    policy_notes = ('Terms art. 6(1): users may not use, reproduce, adapt, translate, repost or '
                    'distribute any site content or information without permission, except as the '
                    'Copyright Act allows. Translation is named explicitly, and translating is the '
                    'point of this tool, so it is not crawled until LIFULL agrees or the owner decides '
                    'otherwise.')
    detail_re = re.compile(r'homes\.co\.jp/(?:kodate|tochi|mansion)/b-(?P<id>\d+)/?(?:$|[?#])')
    PATHS = {'detached_house': 'kodate/chuko', 'land': 'tochi', 'condominium': 'mansion/chuko'}

    def search_targets(self, munis, categories=('detached_house', 'land')):
        return [SearchTarget(f'https://www.homes.co.jp/{self.PATHS[c]}/{PREF_SLUG[m.pref]}/{m.slug}/list/',
                             c, f'{m.name_en} / {c}')
                for m in munis for c in categories]
