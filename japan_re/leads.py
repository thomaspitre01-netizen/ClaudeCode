"""Leads: the short list worth scanning first.

Thomas's criteria (27 Sep 2026): a house, land, a building or a flat around Kichijoji,
Nakano, Koenji or Kamakura; ownership (freehold) preferred; under ¥100M and ideally
¥50M or less; older or traditional houses to renovate are the most interesting.
Nothing is hidden for needing work - age and renovation push a property *up*.

Each lead gets a score from these rules and a list of the reasons, so the ranking can
be read and argued with rather than trusted blindly.
"""
from __future__ import annotations

import datetime as dt

from .translate import summary_en

MAX_PRICE = 100_000_000
IDEAL_PRICE = 50_000_000

# An area matches on the municipality, a nearby station (≤ 20 min walk) or the
# neighbourhood name, because Koenji and Kichijoji are stations, not municipalities.
AREAS = {
    'Kichijoji': dict(municipalities=('Musashino',), stations=('Kichijoji', 'Inokashira-koen'),
                      neighborhoods=('吉祥寺', '御殿山', '井の頭')),
    'Nakano':    dict(municipalities=('Nakano',), stations=('Nakano', 'Shin-Nakano', 'Nakano-sakaue',
                                                            'Nakano-shimbashi', 'Nakano-fujimicho'),
                      neighborhoods=()),
    'Koenji':    dict(municipalities=(), stations=('Koenji', 'Shin-Koenji', 'Higashi-Koenji'),
                      neighborhoods=('高円寺', '梅里', '和田')),
    'Kamakura':  dict(municipalities=('Kamakura',), stations=('Kamakura', 'Kita-Kamakura'),
                      neighborhoods=()),
}
TYPES = ('detached_house', 'traditional_house', 'kominka', 'machiya', 'land', 'entire_building',
         'mixed_use', 'condominium')
WALK_MAX = 20


def _stations(conn, property_id) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in conn.execute('SELECT s.station_en, s.station_ja, s.walk_min FROM listings l '
                          'JOIN listing_stations s ON s.listing_id = l.id WHERE l.property_id = ?',
                          (property_id,)):
        name = s['station_en'] or s['station_ja']
        if name and s['walk_min'] is not None:
            out[name] = min(out.get(name, 999), s['walk_min'])
    return out


def area_of(r, stations: dict[str, int]) -> str | None:
    hood = r['neighborhood_ja'] or r['address_ja'] or ''
    for area, rule in AREAS.items():
        if r['municipality'] in rule['municipalities']:
            return area
        if any(stations.get(s, 999) <= WALK_MAX for s in rule['stations']):
            return area
        if r['municipality'] in ('Suginami', 'Musashino', 'Mitaka') and \
                any(n in hood for n in rule['neighborhoods']):
            return area
    return None


def score(r, new_since: str | None = None) -> tuple[int, list[str]]:
    s, why = 0, []
    price = r['price_jpy']
    if price <= IDEAL_PRICE:
        s += 40; why.append('≤ ¥50M')
    elif price <= 75_000_000:
        s += 20
    else:
        s += 5
    t = r['property_type']
    if t in ('traditional_house', 'kominka', 'machiya'):
        s += 30; why.append(t.replace('_', ' '))
    elif t in ('detached_house', 'land', 'entire_building', 'mixed_use'):
        s += 10
    year = r['year_built']
    if year and year < 1981:
        s += 15; why.append(f'pre-1981 ({year})')
    elif year and year < 2000:
        s += 5
    cond = r['condition']
    if cond in ('major_renovation', 'full_renovation', 'derelict_rebuild'):
        s += 15; why.append(cond.replace('_', ' '))
    elif cond == 'minor_renovation':
        s += 5
    land = r['land_area_m2'] or 0
    if land >= 150:
        s += 10; why.append(f'{land:,.0f} m² land')
    elif land >= 100:
        s += 5
    if r['land_rights'] and r['land_rights'] != 'freehold':
        s -= 25; why.append(f'NOT freehold ({r["land_rights"]})')
    if r['rebuild_prohibited']:
        s -= 10; why.append('rebuild not permitted')
    if new_since and r['first_seen'] and r['first_seen'] >= new_since:
        why.append('new this week')
    return s, why


def find(conn, areas=None, max_price: int = MAX_PRICE, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        f'SELECT * FROM v_properties WHERE status = ? AND price_jpy IS NOT NULL AND price_jpy <= ? '
        f'AND property_type IN ({",".join("?" * len(TYPES))})', ('active', max_price, *TYPES)).fetchall()
    # 'new this week' only means something once the database is older than a week
    first = conn.execute('SELECT MIN(first_seen) FROM listings').fetchone()[0] or ''
    week_ago = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).isoformat()
    new_since = week_ago if first < week_ago else None
    out = []
    for r in rows:
        area = area_of(r, _stations(conn, r['property_id']))
        if not area or (areas and area not in areas):
            continue
        s, why = score(r, new_since)
        out.append(dict(row=r, area=area, score=s, why=why))
    out.sort(key=lambda x: (-x['score'], x['row']['price_jpy']))
    return out[:limit]


def to_markdown(leads: list[dict]) -> str:
    lines = [f'# Leads ({dt.date.today().isoformat()})', '',
             'Houses, land, buildings and flats under ¥100M around Kichijoji, Nakano, Koenji and '
             'Kamakura. Ranked: ¥50M or less, traditional or older houses to renovate, more land and '
             'freehold come first.', '']
    for area in AREAS:
        group = [x for x in leads if x['area'] == area]
        if not group:
            continue
        lines += [f'## {area} ({len(group)})', '']
        for x in group:
            r = x['row']
            title = r['title_en'] or r['title_ja'] or ''
            lines.append(f'- **#{r["property_id"]}** {summary_en(r)}  ')
            lines.append(f'  {title} · {", ".join(x["why"]) or "fits the criteria"} · '
                         f'[{r["sources"]}]({r["primary_url"]})')
        lines.append('')
    if not leads:
        lines.append('No matching properties yet.')
    return '\n'.join(lines)
