"""Coordinates for listings whose page did not publish any.

Uses the Geospatial Information Authority of Japan's public address search
(msearch.gsi.go.jp), which is free and meant for this. Japanese listings usually
hide the lot number, so most results are chome-level (a few hundred metres):
good enough for a map and for distance-to-station, and recorded as such in
geocode_precision so nobody mistakes the pin for the front door.
"""
from __future__ import annotations

import json
import re
import urllib.parse

from . import db
from .fetch import PoliteClient
from .normalize import nfkc

GSI = 'https://msearch.gsi.go.jp/address-search/AddressSearch?q='


def _query(address_ja: str) -> tuple[str, str]:
    a = nfkc(address_ja).replace(' ', '')
    a = re.sub(r'(以下|地内|他|付近).*$', '', a)
    if re.search(r'丁目\d', a) or re.search(r'\d+-\d+', a):
        return a, 'exact'
    if '丁目' in a:
        return a, 'chome'
    return a, 'town'


def run(conn, client: PoliteClient | None = None, limit: int | None = None, log=print) -> int:
    client = client or PoliteClient(min_delay=1.5)
    rows = conn.execute("SELECT id, address_ja FROM listings WHERE lat IS NULL AND address_ja IS NOT NULL "
                        "AND in_scope = 1" + (f' LIMIT {int(limit)}' if limit else '')).fetchall()
    done = 0
    for r in rows:
        q, precision = _query(r['address_ja'])
        hit = conn.execute('SELECT lat, lng FROM geocode_cache WHERE query = ?', (q,)).fetchone()
        if hit is None:
            page = client.get(GSI + urllib.parse.quote(q))
            lat = lng = matched = None
            if page.ok:
                try:
                    results = json.loads(page.html)
                except ValueError:
                    results = []
                if results:
                    lng, lat = results[0]['geometry']['coordinates']
                    matched = results[0]['properties'].get('title')
            conn.execute('INSERT OR REPLACE INTO geocode_cache VALUES (?,?,?,?,?)',
                         (q, lat, lng, matched, db.now()))
            hit = {'lat': lat, 'lng': lng}
        if hit['lat'] is not None:
            conn.execute("UPDATE listings SET lat = ?, lng = ?, geocode_source = 'gsi', geocode_precision = ? "
                         'WHERE id = ?', (hit['lat'], hit['lng'], precision, r['id']))
            done += 1
        conn.commit()
    log(f'geocoded {done} of {len(rows)} listings')
    return done
