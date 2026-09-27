"""Duplicate detection: the same house listed by three agencies is one property.

Listings are compared only within a municipality (blocking), then scored on the
facts agencies copy from the same registry documents: land area and building area
to the hundredth of a m², construction year, the town/chome, the asking price,
coordinates. Two land areas that both exist and disagree by more than 1% veto a
match outright; that is what separates neighbouring lots in one subdivision,
which otherwise look identical.

Every decision is stored in dedup_matches with its reasons, so a merge can be
read ("same land 285.12 m², same building 142.3 m², same year 1972, same chome")
and undone: mark the pair 'rejected' and it is never merged again.
"""
from __future__ import annotations

import itertools
import json
import math
from collections import defaultdict

from . import db

THRESHOLD = 7.0


def _close(a, b, abs_tol, rel_tol=0.0) -> bool:
    return a is not None and b is not None and abs(a - b) <= max(abs_tol, rel_tol * max(a, b))


def _metres(a, b) -> float | None:
    if None in (a['lat'], a['lng'], b['lat'], b['lng']):
        return None
    dlat = math.radians(b['lat'] - a['lat'])
    dlng = math.radians(b['lng'] - a['lng']) * math.cos(math.radians(a['lat']))
    return 6_371_000 * math.hypot(dlat, dlng)


def score(a, b) -> tuple[float, list[str]]:
    """Similarity of two listing rows. Returns (score, reasons). Negative = vetoed."""
    reasons: list[str] = []
    if a['property_type'] and b['property_type'] and a['property_type'] != b['property_type']:
        # land vs house can be the same plot (古家付き土地 listed both ways); anything
        # else, e.g. condo vs house, cannot.
        if {a['property_type'], b['property_type']} - {'land', 'detached_house', 'traditional_house',
                                                       'kominka', 'machiya'}:
            return -1, ['different property types']
    s = 0.0
    la, lb = a['land_area_m2'], b['land_area_m2']
    if la and lb:
        if _close(la, lb, 0.05):
            s += 4; reasons.append(f'same land {la} m²')
        elif _close(la, lb, 0, 0.01):
            s += 2; reasons.append(f'land within 1% ({la} / {lb} m²)')
        else:
            return -1, [f'land differs ({la} / {lb} m²)']
    ba, bb = a['building_area_m2'], b['building_area_m2']
    if ba and bb:
        if _close(ba, bb, 0.05):
            s += 3; reasons.append(f'same building {ba} m²')
        elif _close(ba, bb, 0, 0.02):
            s += 1.5; reasons.append(f'building within 2% ({ba} / {bb} m²)')
        else:
            s -= 3; reasons.append(f'building differs ({ba} / {bb} m²)')
    if a['year_built'] and b['year_built']:
        if a['year_built'] == b['year_built']:
            s += 2; reasons.append(f'same year {a["year_built"]}')
        elif abs(a['year_built'] - b['year_built']) > 1:
            s -= 2; reasons.append('different year built')
    if a['neighborhood_ja'] and b['neighborhood_ja']:
        if a['neighborhood_ja'] == b['neighborhood_ja']:
            s += 2; reasons.append(f'same area {a["neighborhood_ja"]}')
        elif not (a['neighborhood_ja'] in b['neighborhood_ja'] or b['neighborhood_ja'] in a['neighborhood_ja']):
            s -= 2; reasons.append('different town')
    pa, pb = a['price_jpy'], b['price_jpy']
    if pa and pb:
        if pa == pb:
            s += 2; reasons.append('same price')
        elif _close(pa, pb, 0, 0.10):
            s += 1; reasons.append('price within 10%')   # one agency lags a price cut
    d = _metres(a, b)
    if d is not None:
        if d < 60:
            s += 2; reasons.append(f'{d:.0f} m apart')
        elif d > 500:
            s -= 3; reasons.append(f'{d:.0f} m apart')
    if a['layout_ja'] and a['layout_ja'] == b['layout_ja']:
        s += 0.5; reasons.append(f'same layout {a["layout_ja"]}')
    if not (la and lb) and not (ba and bb):
        s = min(s, THRESHOLD - 0.5)   # never merge on price and address alone
        reasons.append('no area to compare')
    return s, reasons


def run(conn) -> dict:
    rows = conn.execute('SELECT * FROM listings WHERE municipality IS NOT NULL').fetchall()
    rejected = {(r['listing_a'], r['listing_b']) for r in
                conn.execute("SELECT listing_a, listing_b FROM dedup_matches WHERE decision = 'rejected'")}
    blocks = defaultdict(list)
    for r in rows:
        blocks[r['municipality']].append(r)

    parent: dict[int, int] = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    matches = 0
    for block in blocks.values():
        for a, b in itertools.combinations(block, 2):
            if a['url'] == b['url']:
                continue
            key = (min(a['id'], b['id']), max(a['id'], b['id']))
            if key in rejected:
                continue
            s, reasons = score(a, b)
            if s >= THRESHOLD:
                matches += 1
                conn.execute('''INSERT INTO dedup_matches (listing_a, listing_b, score, reasons_json)
                                VALUES (?,?,?,?) ON CONFLICT(listing_a, listing_b) DO UPDATE
                                SET score = excluded.score, reasons_json = excluded.reasons_json''',
                             (*key, s, json.dumps(reasons, ensure_ascii=False)))
                ra, rb = find(a['id']), find(b['id'])
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
    # confirmed pairs from earlier runs always hold
    for r in conn.execute("SELECT listing_a, listing_b FROM dedup_matches WHERE decision = 'confirmed'"):
        ra, rb = find(r['listing_a']), find(r['listing_b'])
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    clusters = defaultdict(list)
    for r in rows:
        clusters[find(r['id'])].append(r)
    merged = 0
    at = db.now()
    for members in clusters.values():
        if len(members) < 2:
            continue
        pids = sorted({m['property_id'] for m in members if m['property_id']})
        keep = pids[0]
        for m in members:
            if m['property_id'] != keep:
                old = m['property_id']
                conn.execute('UPDATE listings SET property_id = ? WHERE id = ?', (keep, m['id']))
                db.event(conn, m['id'], 'property_merged', at, into=keep, was=old)
                merged += 1
        # carry notes/favorites from merged-away properties, then drop them if empty
        for old in pids[1:]:
            conn.execute('''UPDATE properties SET
                              renovation_low_jpy = COALESCE(renovation_low_jpy,
                                  (SELECT renovation_low_jpy FROM properties WHERE id = ?)),
                              renovation_high_jpy = COALESCE(renovation_high_jpy,
                                  (SELECT renovation_high_jpy FROM properties WHERE id = ?)),
                              notes = COALESCE(notes, (SELECT notes FROM properties WHERE id = ?))
                            WHERE id = ?''', (old, old, old, keep))
            conn.execute('INSERT OR IGNORE INTO favorites (property_id, added_at, note) '
                         'SELECT ?, added_at, note FROM favorites WHERE property_id = ?', (keep, old))
            conn.execute('DELETE FROM properties WHERE id = ? AND NOT EXISTS '
                         '(SELECT 1 FROM listings WHERE property_id = ?)', (old, old))
    conn.commit()
    return {'pairs_matched': matches, 'listings_reassigned': merged,
            'properties': conn.execute('SELECT COUNT(*) FROM properties').fetchone()[0],
            'listings': len(rows)}
