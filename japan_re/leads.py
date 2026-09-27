"""Leads: the curated short list built on top of the full database.

Thomas's criteria (brief section 19, 27 Sep 2026), in short:
  * hard cap ¥70M; ideal ≤ ¥50M, sweet spot ¥30-50M; ¥50-70M only when unusually
    interesting, and always flagged as above the ideal budget;
  * land + ownership + character + age + location + renovation potential, never
    newness or luxury: needing ¥30-50M of work is not a penalty;
  * at most a 30-minute walk from the main station of a target area (added 27 Sep);
  * Kichijoji, Nakano, Koenji, Kamakura, Kita-Kamakura first; Mitaka, Nishi-Ogikubo,
    Asagaya, Ogikubo, Higashi-/Shin-Nakano, the streets around Koenji, Zushi and Hayama
    second.

Instead of one opaque score every lead carries plain indicators (price, land, age,
renovation, location, traditional character, freehold), the categories it falls in,
and a one-sentence reason. A hidden weight only decides the order within a list.
"""
from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass, field

from .normalize import nfkc

HARD_MAX = 70_000_000
IDEAL_MAX = 50_000_000
SWEET_MIN = 30_000_000
WALK_MAX = 30            # hard limit: minutes on foot from one of the main stations below

# The main station of each area. A property is in an area when the listing gives a walk
# of WALK_MAX minutes or less to that station, or - when the listing names other stations -
# when its map pin is within a 30-minute walk as the crow flies (80 m/min on the road,
# ~1.3x longer than a straight line, so 1.85 km).
STATIONS = [  # (area, tier, station names as listings write them, (lat, lng))
    ('Kichijoji', 'primary', ('吉祥寺', 'Kichijoji'), (35.7031, 139.5798)),
    ('Koenji', 'primary', ('高円寺', 'Koenji'), (35.7054, 139.6496)),
    ('Nakano', 'primary', ('中野', 'Nakano'), (35.7056, 139.6657)),
    ('Kita-Kamakura', 'primary', ('北鎌倉', 'Kita-Kamakura'), (35.3370, 139.5460)),
    ('Kamakura', 'primary', ('鎌倉', 'Kamakura'), (35.3190, 139.5505)),
    ('Mitaka', 'secondary', ('三鷹', 'Mitaka'), (35.7027, 139.5607)),
    ('Nishi-Ogikubo', 'secondary', ('西荻窪', 'Nishi-Ogikubo'), (35.7038, 139.5993)),
    ('Ogikubo', 'secondary', ('荻窪', 'Ogikubo'), (35.7047, 139.6200)),
    ('Asagaya', 'secondary', ('阿佐ケ谷', '阿佐ヶ谷', 'Asagaya'), (35.7050, 139.6359)),
    ('Higashi-Nakano', 'secondary', ('東中野', 'Higashi-Nakano'), (35.7068, 139.6828)),
    ('Shin-Nakano', 'secondary', ('新中野', 'Shin-Nakano'), (35.6976, 139.6690)),
    ('Zushi', 'secondary', ('逗子', 'Zushi'), (35.2957, 139.5795)),
    ('Zushi', 'secondary', ('逗子・葉山', '新逗子', 'Zushi-Hayama', 'Shin-Zushi'), (35.2944, 139.5840)),
]
M_PER_MIN_STRAIGHT = 80 / 1.3

TYPES = ('detached_house', 'traditional_house', 'kominka', 'machiya', 'land', 'entire_building',
         'mixed_use', 'condominium', 'other')
TRADITIONAL_TYPES = ('traditional_house', 'kominka', 'machiya')
TRADITIONAL_WORDS = ('古民家', '日本家屋', '純和風', '数寄屋', '数奇屋', '茶室', '町家', '町屋', '書院',
                     '土間', '縁側', '欄間', '床の間', '囲炉裏', '土蔵', '瓦屋根', '和風建築')
GARDEN_WORDS = ('庭', 'ガーデン')
UNUSUAL_WORDS = ('アトリエ', '土蔵', '蔵付', '茶室', '店舗付', '店舗併用', '平屋', '洋館', '擁壁', '旗竿', '変形地',
                 '崖', '高台', '眺望', '離れ', '別棟', '二世帯', '工場', '倉庫', '山林', '菜園', '井戸')
WORDS_EN = {'アトリエ': 'atelier', '土蔵': 'kura storehouse', '蔵付': 'with kura', '茶室': 'tea room',
            '店舗付': 'with shop', '店舗併用': 'shop + home', '平屋': 'single-storey', '洋館': 'Western-style house',
            '擁壁': 'retaining wall', '旗竿': 'flag-shaped lot', '変形地': 'irregular plot', '崖': 'slope/cliff',
            '高台': 'hilltop', '眺望': 'views', '離れ': 'annex', '別棟': 'second building', '二世帯': 'two-family',
            '工場': 'workshop', '倉庫': 'storehouse', '山林': 'woodland', '菜園': 'vegetable garden', '井戸': 'well'}
REDEVELOP_WORDS = ('古家付', '古家あり', '更地渡し', '建築条件なし', '分割', '二区画', '2区画', '建替', '建て替え')

GREEN, YELLOW, RED, GREY = '🟢', '🟡', '🔴', '⚪'


@dataclass
class Lead:
    row: dict
    area: str | None
    tier: str | None                      # 'primary' | 'secondary'
    station: str | None = None            # 'Kichijoji, 12 min walk'
    review: str | None = None             # seen | liked | passed
    review_note: str | None = None
    indicators: dict[str, tuple[str, str]] = field(default_factory=dict)   # name -> (dot, text)
    signals: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    weight: int = 0
    is_lead: bool = False
    reason: str = ''

    @property
    def id(self):
        return self.row['property_id']


# ---------------------------------------------------------------- location

def _stations(conn, property_id) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in conn.execute('SELECT s.station_ja, s.station_en, s.walk_min FROM listings l '
                          'JOIN listing_stations s ON s.listing_id = l.id WHERE l.property_id = ?',
                          (property_id,)):
        if s['walk_min'] is None:
            continue
        for name in (s['station_ja'], s['station_en']):
            if name:
                out[nfkc(name)] = min(out.get(nfkc(name), 999), s['walk_min'])
    return out


def _km(a, b) -> float:
    import math
    dy = (a[0] - b[0]) * 111.0
    dx = (a[1] - b[1]) * 111.0 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def locate(r, stations: dict[str, int]) -> tuple[str | None, str | None, str | None]:
    """(area, tier, 'Kichijoji, 12 min walk') for the best main station within WALK_MAX,
    primary areas before secondary ones, else (None, None, None)."""
    best = None
    for area, tier, names, coord in STATIONS:
        walk = min((stations[nfkc(n)] for n in names if nfkc(n) in stations), default=None)
        how = 'walk'
        if walk is None and r.get('lat') and r.get('lng'):
            walk = round(_km((r['lat'], r['lng']), coord) * 1000 / M_PER_MIN_STRAIGHT)
            how = 'walk, estimated from the map'
        if walk is None or walk > WALK_MAX:
            continue
        key = (tier != 'primary', walk)
        if best is None or key < best[0]:
            best = (key, area, tier, f'{names[-1]}, {walk} min {how}')
    return (best[1], best[2], best[3]) if best else (None, None, None)


# ---------------------------------------------------------------- indicators

def _text(r) -> str:
    return nfkc(' '.join(str(r.get(k) or '') for k in ('title_ja', 'description_ja', 'restrictions_ja')))


def land_medians(conn) -> dict[str, float]:
    """Median asking ¥/m² of land per municipality, houses and land only: the yardstick
    for 'the asking price looks attractive relative to the land'."""
    per: dict[str, list[float]] = {}
    for r in conn.execute("SELECT municipality, price_per_m2_land FROM v_properties WHERE status = 'active' "
                          "AND price_per_m2_land > 0 AND property_type IN ('detached_house', 'land', "
                          "'traditional_house', 'kominka', 'machiya')"):
        per.setdefault(r['municipality'], []).append(r['price_per_m2_land'])
    return {m: statistics.median(v) for m, v in per.items() if len(v) >= 5}


def assess(r, area, tier, medians, new_since, text, station=None) -> Lead:
    L = Lead(row=r, area=area, tier=tier, station=station)
    ind, sig = L.indicators, L.signals
    price, ptype = r['price_jpy'], r['property_type']
    is_flat = ptype == 'condominium'

    if price <= IDEAL_MAX:
        ind['Price'] = (GREEN, 'sweet spot ¥30-50M' if price >= SWEET_MIN else 'within target')
        sig.append('price')
    else:
        ind['Price'] = (YELLOW, 'above ideal budget (¥50-70M)')

    land = r['land_area_m2'] or 0
    if is_flat:
        ind['Land'] = (RED, 'flat: no land of its own')
    elif land >= 200:
        ind['Land'] = (GREEN, f'large ({land:,.0f} m²)'); sig.append('land')
    elif land >= 120:
        ind['Land'] = (YELLOW, f'{land:,.0f} m²')
    elif land:
        ind['Land'] = (RED, f'small ({land:,.0f} m²)')
    else:
        ind['Land'] = (GREY, 'unknown')

    year = r['year_built']
    if ptype == 'land':
        ind['Age'] = (GREY, 'land')
    elif year and year < 1981:
        ind['Age'] = (GREEN, f'older, pre-1981 ({year})'); sig.append('age')
    elif year and year < 2000:
        ind['Age'] = (YELLOW, str(year))
    elif year:
        ind['Age'] = (RED, f'recent ({year})')
    else:
        ind['Age'] = (GREY, 'unknown')

    cond = r['condition']
    derelict = cond == 'derelict_rebuild' or any(w in text for w in ('古家付', '古家あり', '上物あり'))
    if cond in ('major_renovation', 'full_renovation') or (derelict and ptype != 'land'):
        ind['Renovation'] = (GREEN, 'high potential: ' + (cond or 'derelict').replace('_', ' '))
        sig.append('renovation')
    elif cond == 'minor_renovation' or (year and year < 1990 and ptype != 'land'):
        ind['Renovation'] = (YELLOW, 'some work likely')
    elif cond == 'move_in_ready':
        ind['Renovation'] = (RED, 'move-in ready')
    else:
        ind['Renovation'] = (GREY, 'unknown' if ptype != 'land' else 'land')

    ind['Location'] = ((GREEN, f'target area ({area})') if tier == 'primary' else
                       (YELLOW, f'secondary area ({area})') if tier == 'secondary' else (RED, 'outside'))
    if tier == 'primary':
        sig.append('location')

    trad_word = next((w for w in TRADITIONAL_WORDS if w in text), None)
    if ptype in TRADITIONAL_TYPES:
        ind['Traditional character'] = (GREEN, ptype.replace('_', ' ')); sig.append('traditional')
    elif trad_word and not is_flat:
        ind['Traditional character'] = (YELLOW, f'mentions {trad_word}')
    else:
        ind['Traditional character'] = (GREY, '-')

    rights = r['land_rights']
    if rights == 'freehold' and not is_flat:
        ind['Freehold'] = (GREEN, 'freehold land'); sig.append('freehold')
    elif rights == 'freehold':
        ind['Freehold'] = (YELLOW, 'freehold share of the block')
    elif rights:
        ind['Freehold'] = (RED, rights)
    else:
        ind['Freehold'] = (GREY, 'unknown')

    # extra signals shown in the reason and the categories
    extras = []
    med = medians.get(r['municipality'])
    ppm = r['price_per_m2_land']
    if med and ppm and not is_flat and ppm <= 0.8 * med:
        extras.append(f'¥{ppm / 1000:,.0f}k/m² land vs ¥{med / 1000:,.0f}k local median')
        sig.append('land_value')
    if derelict:
        extras.append('building has little value, the land is the point'); sig.append('land_value')
    if r['initial_price_jpy'] and price < r['initial_price_jpy']:
        extras.append(f'price cut from ¥{r["initial_price_jpy"] / 1e6:,.1f}M'); sig.append('price_cut')
    if not is_flat and any(w in text for w in GARDEN_WORDS):
        extras.append('garden'); sig.append('garden')
    unusual = [w for w in UNUSUAL_WORDS if w in text]
    if unusual:
        extras.append('unusual: ' + ', '.join(WORDS_EN.get(w, w) for w in unusual[:3])); sig.append('unusual')
    if any(w in text for w in REDEVELOP_WORDS):
        extras.append('redevelopment potential'); sig.append('redevelop')
    if r['rebuild_prohibited']:
        extras.append('rebuild not permitted (再建築不可)')
    if new_since and r['first_seen'] and r['first_seen'] >= new_since:
        sig.append('new')
    L.reason = _reason(r, area, extras, station)

    # ----- is it a lead? hard cap and area are checked by the caller
    # 'core' signals are the ones the brief is about; garden/unusual only break ties
    core = [s for s in set(sig) if s in ('age', 'renovation', 'traditional', 'land_value', 'redevelop',
                                         'price_cut')]
    strong = core + [s for s in set(sig) if s in ('land', 'freehold', 'garden', 'unusual')]
    if is_flat:
        # a flat needs to be cheap and old or in need of work to beat a house with land
        L.is_lead = price <= IDEAL_MAX and ('age' in sig or 'renovation' in sig)
    elif price <= IDEAL_MAX:
        L.is_lead = len(core) >= 1 and len(strong) >= 3 or len(core) >= 2
    else:
        L.is_lead = len(core) >= 2 and 'land' in sig    # ¥50-70M: only when particularly interesting

    # ----- order within a list: land + ownership + character + age + location + work
    w = {'price': 25, 'land': 20, 'age': 15, 'renovation': 15, 'traditional': 25, 'freehold': 15,
         'location': 15, 'land_value': 15, 'price_cut': 10, 'garden': 5, 'unusual': 5, 'redevelop': 5,
         'new': 5}
    L.weight = sum(w.get(s, 0) for s in set(sig))
    if SWEET_MIN <= price <= IDEAL_MAX:
        L.weight += 5
    if is_flat:
        L.weight -= 25
    if rights and rights != 'freehold':
        L.weight -= 20
    if r['rebuild_prohibited']:
        L.weight -= 10

    cats = L.categories
    if L.is_lead:
        if 'new' in sig:
            cats.append('New Leads')
        if 'renovation' in sig or ('age' in sig and ind['Renovation'][0] != RED):
            cats.append('Renovation Opportunities')
        if not is_flat and ('land' in sig or 'land_value' in sig or 'redevelop' in sig):
            cats.append('Land Opportunities')
        if 'traditional' in sig or ind['Traditional character'][0] == YELLOW:
            cats.append('Traditional Properties')
        if 'price_cut' in sig or 'land_value' in sig:
            cats.append('Price Opportunities')
        if 'unusual' in sig or r['rebuild_prohibited']:
            cats.append('Unusual / Hidden Opportunities')
        if not cats:
            cats.append('Other Leads')
    elif strong:
        cats.append('Watchlist')
    return L


TYPE_EN = {'detached_house': 'House', 'traditional_house': 'Traditional house', 'kominka': 'Kominka',
           'machiya': 'Machiya', 'land': 'Land', 'entire_building': 'Entire building',
           'mixed_use': 'Mixed-use building', 'condominium': 'Apartment', 'other': 'Property'}


def _reason(r, area, extras, station=None) -> str:
    bits = [f'¥{r["price_jpy"] / 1e6:,.1f}M {TYPE_EN.get(r["property_type"], "property").lower()}']
    if r['land_area_m2'] and r['property_type'] != 'condominium':
        bits.append(f'with {r["land_area_m2"]:,.0f} m² of land')
    bits.append(f'in {area}')
    s = ' '.join(bits)
    if r['year_built']:
        s += f', built {r["year_built"]}'
    if r['condition'] in ('major_renovation', 'full_renovation', 'derelict_rebuild'):
        s += ', ' + {'major_renovation': 'needs major renovation', 'full_renovation': 'needs full renovation',
                     'derelict_rebuild': 'building near end of life'}[r['condition']]
    if station:
        name, walk = station.split(', ', 1)
        est = ' (est. from the map)' if 'estimated' in walk else ''
        s += f', {walk.split(" min")[0]} min walk from {name}{est}'
    if extras:
        s += '; ' + '; '.join(extras)
    return s + '.'


# ---------------------------------------------------------------- queries

# A lead can fit several categories but is shown once, under the first that fits in
# this order; the card lists the others as tags.
CATEGORY_ORDER = ('New Leads', 'Traditional Properties', 'Renovation Opportunities', 'Land Opportunities',
                  'Price Opportunities', 'Unusual / Hidden Opportunities', 'Other Leads', 'Watchlist')


def main_category(L: 'Lead') -> str:
    return next(c for c in CATEGORY_ORDER if c in L.categories)


def find(conn, areas: list[str] | None = None, include_secondary: bool = True,
         max_price: int = HARD_MAX, include_passed: bool = False) -> list[Lead]:
    """Every active property under the cap in the chosen areas, assessed. Leads and
    watchlist entries both come back; `is_lead` tells them apart."""
    max_price = min(max_price, HARD_MAX)
    rows = conn.execute(
        f"SELECT * FROM v_properties WHERE status = 'active' AND price_jpy IS NOT NULL AND price_jpy <= ? "
        f"AND property_type IN ({','.join('?' * len(TYPES))})", (max_price, *TYPES)).fetchall()
    medians = land_medians(conn)
    reviews = {x['property_id']: (x['state'], x['note']) for x in conn.execute('SELECT * FROM reviews')}
    first = conn.execute('SELECT MIN(first_seen) FROM listings').fetchone()[0] or ''
    week_ago = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).isoformat()
    new_since = week_ago if first < week_ago else None   # 'new' means nothing in week one
    out = []
    for row in rows:
        r = dict(row)
        area, tier, station = locate(r, _stations(conn, r['property_id']))
        if not area or (tier == 'secondary' and not include_secondary):
            continue
        if areas and area not in areas:
            continue
        text = _text(r) + ' ' + _listing_text(conn, r['property_id'])
        L = assess(r, area, tier, medians, new_since, text, station)
        rv = reviews.get(r['property_id'])
        if rv:
            L.review, L.review_note = rv
        if L.review == 'passed' and not include_passed:
            continue
        if L.categories:
            out.append(L)
    # unchecked first within each list, so what is left to look at is on top
    out.sort(key=lambda L: (not L.is_lead, L.review == 'passed', L.review in ('seen', 'liked'),
                            L.tier != 'primary', -L.weight, L.row['price_jpy']))
    return out


def _listing_text(conn, property_id) -> str:
    return nfkc(' '.join(x[0] or '' for x in conn.execute(
        'SELECT description_ja FROM listings WHERE property_id = ?', (property_id,))))


# ---------------------------------------------------------------- output

def card(L: Lead) -> list[str]:
    r = L.row
    title = f'¥{r["price_jpy"] / 1e6:,.1f}M — {TYPE_EN.get(r["property_type"], "Property")} — {L.area}'
    if L.indicators['Price'][0] != GREEN:
        title += ' (above ideal budget)'
    mark = {'seen': ' · ✓ seen', 'liked': ' · ♥ liked', 'passed': ' · ✗ passed'}.get(L.review, ' · ○ not checked yet')
    lines = [f'### {title}{mark}', '']
    if L.review_note:
        lines += [f'_Your note: {L.review_note}_', '']
    facts = []
    if r['land_area_m2'] and r['property_type'] != 'condominium':
        facts.append(f'Land: {r["land_area_m2"]:,.0f} m²')
    if r['building_area_m2']:
        facts.append(f'Building: {r["building_area_m2"]:,.0f} m²')
    if r['year_built']:
        facts.append(f'Built: {r["year_built"]}')
    if L.station:
        facts.append(f'Station: {L.station}')
    nearest = (r['nearest_station'] or '').split(' / ')[-1]
    if nearest and r['station_walk_min'] is not None and not (L.station or '').startswith(nearest):
        facts.append(f'Nearest: {nearest}, {r["station_walk_min"]} min')
    facts.append(f'Condition: {(r["condition"] or "unknown").replace("_", " ")}')
    facts.append(f'Land ownership: {r["land_rights"] or "unknown"}')
    lines.append(' · '.join(facts) + '  ')
    lines.append(' '.join(f'{name}: {dot}' for name, (dot, _) in L.indicators.items()) + '  ')
    lines.append(f'**Why:** {L.reason}  ')
    others = [c for c in L.categories if c != main_category(L)]
    if others:
        lines.append(f'Also: {", ".join(others)}  ')
    title_ja = r['title_ja'] or ''
    lines.append(f'#{r["property_id"]} · {title_ja} · first seen {(r["first_seen"] or "")[:10]} · '
                 f'[Open listing]({r["primary_url"]}) ({r["sources"]})')
    lines.append('')
    return lines


def to_markdown(found: list[Lead]) -> str:
    leads = [L for L in found if L.is_lead]
    unchecked = sum(1 for L in leads if not L.review)
    out = [f'# Leads · {dt.date.today():%d %b %Y}', '',
           f'{len(leads)} leads ({unchecked} not checked yet) and {len(found) - len(leads)} on the watchlist. Hard limits: ¥70M and a 30-minute walk from a main station; ¥50M or less '
           'preferred. Ranked by land, ownership, character, age, location and renovation potential. '
           'Indicator order: Price, Land, Age, Renovation, Location, Traditional character, Freehold '
           '(🟢 good · 🟡 so-so · 🔴 against · ⚪ unknown).', '']
    for cat in CATEGORY_ORDER:
        group = [L for L in found if main_category(L) == cat]
        if cat == 'New Leads' and not group:
            continue
        if not group:
            continue
        out += [f'## {cat} ({len(group)})', '']
        for L in group:
            out += card(L)
    if not found:
        out.append('No matching properties yet.')
    return '\n'.join(out)


def to_json(found: list[Lead]) -> list[dict]:
    keys = ('property_id', 'price_jpy', 'property_type', 'municipality', 'land_area_m2', 'building_area_m2',
            'year_built', 'condition', 'land_rights', 'nearest_station', 'station_walk_min', 'lat', 'lng',
            'primary_url', 'sources', 'first_seen', 'title_ja', 'title_en', 'thumbnail_url')
    return [dict({k: L.row.get(k) for k in keys}, area=L.area, area_tier=L.tier, main_station=L.station,
                 review=L.review, review_note=L.review_note, is_lead=L.is_lead,
                 categories=L.categories, main_category=main_category(L), reason=L.reason, weight=L.weight,
                 indicators={k: {'dot': d, 'text': t} for k, (d, t) in L.indicators.items()})
            for L in found]
