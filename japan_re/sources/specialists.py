"""Specialist and off-portal sources: where the unusual houses turn up.

R不動産 (Real Kamakura / Real Tokyo Estate) curates character properties, old houses
and renovation projects, often written up at length. 家いちば is an owner-to-buyer
board where neglected houses and akiya are listed by their owners, frequently
never reaching the portals.

To add a local agency, subclass `Source` with its listing index as the search
target and a `detail_re` that matches its property pages; the generic reader in
base.py handles the rest. Record the robots/terms check in SOURCES.md.
"""
from __future__ import annotations

import re
import urllib.parse

from ..normalize import nfkc
from .base import BeautifulSoup, ParsedListing, SearchTarget, Source, _text, coordinates, images


class RealKamakura(Source):
    id = 'real_kamakura'
    name = '鎌倉R不動産 (Real Kamakura Estate)'
    base_url = 'https://www.realkamakuraestate.jp/'
    kind = 'specialist'
    policy = 'allowed'
    policy_notes = 'No robots.txt (404). No terms-of-use page linked from the site; privacy policy only.'
    enabled_by_default = True
    detail_re = re.compile(r'realkamakuraestate\.jp/estate\.php\?n=(?P<id>\d+)')
    max_pages_per_target = 40
    per_municipality = False

    def search_targets(self, munis, categories=None):
        # The site covers Kamakura/Zushi/Hayama/Shonan only, so one index serves all
        # municipalities; out-of-area results are marked out of scope when stored.
        # type[]=2 is 売買 (for sale); mode=all mixes in rentals.
        return [SearchTarget(f'{self.base_url}estate_search.php?mode=key&type[]=2', 'detached_house',
                             'for sale')]

    def canonical_url(self, url):
        m = self.detail_re.search(url)
        return f'{self.base_url}estate.php?n={m.group("id")}' if m else url

    def parse_detail(self, pages, category_hint):
        # One index holds houses, flats and land alike; the spec table tells them apart.
        out = super().parse_detail(pages, category_hint)
        g = out.pairs.get
        if re.search(r'\d', g('所在階', '')) or re.search(r'\d', g('修繕積立金', '')):
            out.category_hint = 'condominium'
        elif not g('建物面積') and g('敷地面積'):
            out.category_hint = 'land'
        return out


class RealTokyo(RealKamakura):
    id = 'real_tokyo'
    name = '東京R不動産 (Real Tokyo Estate)'
    base_url = 'https://www.realtokyoestate.co.jp/'
    policy_notes = 'No robots.txt (404). Same platform as Real Kamakura; no terms page found.'
    detail_re = re.compile(r'realtokyoestate\.co\.jp/estate\.php\?n=(?P<id>\d+)')


class Ieichiba(Source):
    id = 'ieichiba'
    name = '家いちば (owner-direct marketplace)'
    base_url = 'https://www.ieichiba.com/'
    kind = 'marketplace'
    policy = 'allowed'
    policy_notes = 'No robots.txt (404). No terms link visible on the board pages checked.'
    enabled_by_default = True
    # /project/P202600274長和町大門U  (id + place name, URL-encoded)
    detail_re = re.compile(r'ieichiba\.com/project/(?P<id>P\d{6,})')
    per_municipality = False
    max_pages_per_target = 40
    PREF_PAGES = {'Tokyo': 'tokyo', 'Kanagawa': 'kanagawa'}

    def search_targets(self, munis, categories=None):
        # The board is nationwide; its prefecture pages (/area/kanagawa) hold only that
        # prefecture's posts. Out-of-area ones among them are stored as out of scope.
        prefs = sorted({m.pref for m in munis})
        return [SearchTarget(f'{self.base_url}area/{self.PREF_PAGES[p]}', 'detached_house', f'{p} board')
                for p in prefs if p in self.PREF_PAGES]

    def next_page(self, html, page_url):
        # pager links are icons (/area/kanagawa/page/2) with no text to recognise
        m = re.search(r'/page/(\d+)/?$', page_url)
        n = int(m.group(1)) + 1 if m else 2
        base = page_url[:m.start()] if m else page_url.rstrip('/')
        path = urllib.parse.urlsplit(base).path
        if f'href="{path}/page/{n}"' in html:
            return f'{base}/page/{n}'
        return None

    # The listing facts are free text in the owner's post ("土地：218坪（更地）"), the
    # price sits in its own block, and the page's only <dl>s are the site's region menu.
    _LINE = re.compile(r'^[ \t]*[【\[]?([^：:\n【】]{1,12})[】\]]?[ \t]*[：:][ \t]*(.+?)[ \t]*$', re.M)
    _LABELS = {'場所': '所在地', '所在地': '所在地', '住所': '所在地', '希望価格': '価格',
               '価格': '価格', '土地': '土地面積', '土地面積': '土地面積', '建物': '建物面積',
               '建物面積': '建物面積', '延床面積': '建物面積', '構造': '構造', '築年': '築年月',
               '築年数': '築年数', '建築年': '築年月', '現況': '現況', '間取り': '間取り',
               '接道': '接道状況', '用途地域': '用途地域', '地目': '地目'}

    def parse_detail(self, pages, category_hint):
        url, html = pages[0]
        soup = BeautifulSoup(html, 'html.parser')
        out = ParsedListing(url=url, source_id=self.id, source_listing_id=self.listing_id(url),
                            category_hint=category_hint)
        out.title = _text(soup.find('h1')) or None
        out.images = images(soup, url)
        out.lat, out.lng = coordinates(html)
        bodies = [b.get_text('\n', strip=True) for b in soup.find_all('p', class_=re.compile(r'^page__body(-overview)?$'))]
        text = '\n'.join(nfkc(line) for b in bodies for line in b.splitlines())   # nfkc folds newlines
        for label, value in self._LINE.findall(text):
            key = self._LABELS.get(label.strip())
            if key and value.strip() and key not in out.pairs:
                out.pairs[key] = value.strip()
        price = soup.find('div', class_='page__body-price')
        if price and price.find('span'):
            out.pairs['価格'] = _text(price.find('span'))
        addr = _text(soup.find('a', class_='page__address'))
        loc = out.pairs.get('所在地', '')
        if addr and not loc.startswith(addr[:3]):      # '守谷' -> '千葉県勝浦市守谷'
            out.pairs['所在地'] = addr + loc
        tags = [_text(b) for b in soup.find_all('button', class_='categories__item')]
        if tags:
            out.pairs['カテゴリ'] = ' '.join(tags)
        out.description = text or None
        building, state = out.pairs.get('建物面積', ''), out.pairs.get('現況', '')
        if building.startswith('なし') or '更地' in state or '更地' in (out.title or ''):
            out.category_hint = 'land'
        return out
