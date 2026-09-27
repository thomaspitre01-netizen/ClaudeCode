"""The three national portals. Between them they carry most agency stock in Kanto.

Search URLs and detail-link patterns were written from the sites' public URL
structure; the first live crawl is what confirms them (a wrong slug shows up as a
404 or an empty target in the crawl log, not as bad data).
"""
from __future__ import annotations

import re
import urllib.parse

from ..normalize import nfkc, parse_price
from .base import BeautifulSoup, SearchTarget, Source

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

    # The browse pages (/chukoikkodate/tokyo/sc_musashino/) are open to crawlers; the
    # /jj/bukken/ichiran/JJ012FC001/ search form is disallowed in robots.txt.
    PATHS = {'detached_house': 'chukoikkodate', 'land': 'tochi', 'condominium': 'ms/chuko'}
    SLUG_EXCEPTIONS = {'14301': 'miuragun'}     # Hayama is listed as 三浦郡

    def suumo_slug(self, m) -> str:
        return self.SLUG_EXCEPTIONS.get(m.code) or re.sub(r'-(ku|city|town|village|shi|machi)$', '', m.slug)

    # Where Thomas only wants the streets around certain stations (27 Sep 2026: "don't
    # include Suginami, keep Koenji"; "stay on Kamakura or Kita-Kamakura"), read the
    # station pages (/chukoikkodate/tokyo/ek_13930/) instead of the whole municipality.
    STATION_ONLY = {
        '13115': [('ek_13930', 'Koenji'), ('ek_19470', 'Shin-Koenji'), ('ek_31910', 'Higashi-Koenji')],
        '14204': [('ek_08890', 'Kamakura'), ('ek_11100', 'Kita-Kamakura')],
    }

    def search_targets(self, munis, categories=('detached_house', 'land')):
        out = []
        for m in munis:
            places = ([(code, name) for code, name in self.STATION_ONLY[m.code]] if m.code in self.STATION_ONLY
                      else [(f'sc_{self.suumo_slug(m)}', m.name_en)])
            for code, name in places:
                for cat in categories:
                    out.append(SearchTarget(f'https://suumo.jp/{self.PATHS[cat]}/{PREF_SLUG[m.pref]}/{code}/',
                                            cat, f'{name} / {cat}'))
        return out

    # Skip before fetching (Thomas, 27 Sep 2026): over the ¥150M hard cap, more than a
    # 30-minute walk from any station (or bus only), no photos, or SUUMO's "nearby"
    # suggestions from other areas (?fmlg=), which their own area's crawl covers.
    MAX_PRICE = 150_000_000
    MAX_WALK = 30

    def detail_links(self, html, page_url):
        soup = BeautifulSoup(html, 'html.parser')
        keep, self.skipped = [], {}
        cards = soup.find_all('div', class_='property_unit')
        if not cards:                      # page layout changed: fall back to every link
            return super().detail_links(html, page_url)
        for card in cards:
            a = next((x for x in card.find_all('a', href=True) if self.detail_re.search(
                urllib.parse.urljoin(page_url, x['href']))), None)
            if not a:
                continue
            href = urllib.parse.urljoin(page_url, a['href'])
            why = self.skip_reason(card, href)
            if why:
                self.skipped[why] = self.skipped.get(why, 0) + 1
                continue
            href = self.canonical_url(href)
            if href not in keep:
                keep.append(href)
        return keep

    def skip_reason(self, card, href) -> str | None:
        if 'fmlg=' in href:
            return 'nearby suggestion'
        fields = {nfkc(dt.get_text(strip=True)): nfkc(dd.get_text(' ', strip=True))
                  for dl in card.find_all('dl') for dt, dd in zip(dl.find_all('dt'), dl.find_all('dd'))}
        price = parse_price(fields.get('販売価格') or fields.get('価格'))[0]
        if price and price > self.MAX_PRICE:
            return 'over ¥150M'
        access = fields.get('沿線・駅') or ''
        walks = [int(x) for x in re.findall(r'徒歩\s*(\d+)\s*分', access)]
        if walks and min(walks) > self.MAX_WALK:
            return 'over 30 min walk'
        if access and not walks and 'バス' in access:
            return 'bus only'
        photos = [i for i in card.find_all('img') if 'suumo.com' in (i.get('rel') and ' '.join(i.get('rel'))
                                                                      or i.get('src') or '')]
        if not photos:
            return 'no photos'
        return None

    def canonical_url(self, url):
        url = super().canonical_url(url).split('?')[0]
        m = re.search(r'^(.*?nc_\d+/)', url)
        return m.group(1) if m else url

    # The /bukkengaiyo/ spec tab repeats what the main page already carries (checked
    # 27 Sep 2026: identical parsed record with and without it), so it is not fetched;
    # that halves the requests per listing.

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
