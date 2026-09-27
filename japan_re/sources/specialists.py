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

from .base import SearchTarget, Source


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
        return [SearchTarget(f'{self.base_url}estate_search.php?mode=all', 'detached_house',
                             'all listings')]

    def canonical_url(self, url):
        m = self.detail_re.search(url)
        return f'{self.base_url}estate.php?n={m.group("id")}' if m else url


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
    max_pages_per_target = 15   # nationwide board: read the newest pages, keep in-scope ones

    def search_targets(self, munis, categories=None):
        return [SearchTarget(f'{self.base_url}board', 'detached_house', 'board')]
