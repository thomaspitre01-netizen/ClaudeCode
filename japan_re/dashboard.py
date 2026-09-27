"""The private dashboard: one self-contained HTML page (map, filters, results, Leads) built
from the database. Read-only: it never writes to the DB.

    python -m japan_re dashboard --out dashboard.html

The page embeds its data as JSON, so it works as a file or as a published Artifact. It can't
load map tiles or listing photos (the Artifact sandbox blocks other hosts), so the map is drawn
from the station areas themselves and each listing links out to its source.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

from . import leads

HARD_MAX = 150_000_000   # the overall budget cap; nothing above it is worth showing
TEMPLATE = Path(__file__).with_name('dashboard.html')

KEYS = ('property_id', 'property_type', 'title_ja', 'title_en', 'municipality', 'municipality_ja',
        'neighborhood_ja', 'address_ja', 'lat', 'lng', 'price_jpy', 'initial_price_jpy', 'land_area_m2',
        'building_area_m2', 'year_built', 'layout_ja', 'structure', 'condition', 'condition_evidence',
        'land_rights', 'rebuild_prohibited', 'station_walk_min', 'nearest_station', 'price_per_m2_land',
        'est_acquisition_cost_jpy', 'first_seen', 'sources', 'primary_url', 'agency_name')


def _compact(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


DESC_MAX = 1500
# Where the listing's own text ends and the portal's page furniture (photo captions, the
# spec table, agency seminars) begins.
CUT = ('※写真に誤り', '※映像に誤り', '特徴ピックアップ', '物件詳細情報', 'イベント情報', '~地域密着',
       '※当物件の一部画像', '連絡希望時間')
CONTACT = re.compile(r'お問い?合せ先\s*(?P<company>.{1,60}?)\s*TEL[:：]\s*(?P<phone>[\d-]{9,})'
                     r'(?:.{0,160}?営業時間[:：]\s*(?P<hours>.{1,40}?)\s*/\s*定休日[:：]\s*(?P<closed>\S+))?')
PERSON = re.compile(r'担当(?:者)?(?:[:：]\s*|\s+)([一-龥][一-龥ぁ-んァ-ヶ]{0,4}(?:\s?[一-龥ぁ-んァ-ヶ]{1,5})?)')
EMAIL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+')
TRANSLATIONS = 'translations_en.json'   # {sha1(description_ja)[:16]: English}, next to the DB
PHOTOS = 'photos.json'                  # {property_id: [data: URI, ...]}, from `japan_re photos`


def clean_description(text: str) -> str:
    text = ' '.join((text or '').split())
    cut = min([i for i in (text.find(m) for m in CUT) if i > 0] + [len(text)])
    text = text[:cut].strip(' -')
    return text[:DESC_MAX] + '…' if len(text) > DESC_MAX else text


def desc_key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def contact(text: str) -> dict:
    """Agency contact details as the listing states them (SUUMO's 'お問い合せ先' block)."""
    out = {}
    m = CONTACT.search(text or '')
    if m:
        out.update({k: v.strip() for k, v in m.groupdict().items() if v})
    p = PERSON.search(text or '')
    if p:
        name = re.sub(r'^(宅建|宅地建物取引士)\s*|\s*(年齢|資格|趣味|出身).*$', '', p.group(1)).strip()
        if name and not re.search(r'担当|が|お|ご', name):
            out['person'] = name
    emails = sorted(set(EMAIL.findall(text or '')))
    if emails:
        out['emails'] = emails
    return out


def _extras(conn, property_id, translations: dict) -> dict:
    """Every source's link, the agency's contact details and the listing text (Japanese,
    plus English where a translation exists), so a listing can be judged without the portal."""
    rows = conn.execute('SELECT source_id, url, agency_name, agency_phone, description_ja FROM listings '
                        "WHERE property_id = ? ORDER BY source_id = 'suumo', id", (property_id,)).fetchall()
    links = [{'source': r['source_id'], 'url': r['url']} for r in rows if r['url']]
    raw = max((r['description_ja'] or '' for r in rows), key=len)
    c = contact(raw)
    c.setdefault('phone', next((r['agency_phone'] for r in rows if r['agency_phone']), None))
    c.setdefault('company', next((r['agency_name'] for r in rows if r['agency_name']), None))
    desc = clean_description(raw)
    return _compact({'links': links, 'contact': _compact(c) or None, 'description_ja': desc or None,
                     'description_en': translations.get(desc_key(desc)) if desc else None})


def build(conn, translations: dict | None = None, photos: dict | None = None) -> dict:
    translations, photos = translations or {}, photos or {}
    rows = conn.execute("SELECT * FROM v_properties WHERE status = 'active' AND in_scope = 1 "
                        'AND price_jpy IS NOT NULL AND price_jpy <= ?', (HARD_MAX,)).fetchall()
    props = []
    for row in rows:
        r = dict(row)
        area, tier, station = leads.locate(r, leads._stations(conn, r['property_id']))
        p = {k: r[k] for k in KEYS}
        p.update(area=area, tier=tier, main_station=station, photos=photos.get(str(r['property_id'])),
                 **_extras(conn, r['property_id'], translations))
        props.append(_compact(p))
    found = leads.find(conn)
    lead_rows = [_compact({k: v for k, v in x.items() if k not in ('thumbnail_url',)})
                 for x in leads.to_json(found)]
    stations = [{'area': a, 'tier': t, 'ja': names[0], 'lat': c[0], 'lng': c[1]}
                for a, t, names, c in leads.STATIONS]
    return {
        'generated': dt.datetime.now(dt.timezone.utc).isoformat(timespec='minutes'),
        'walk_max': leads.WALK_MAX,
        'lead_max': leads.HARD_MAX,
        'radius_m': leads.WALK_MAX * leads.M_PER_MIN_STRAIGHT,
        'stations': stations,
        'properties': props,
        'leads': lead_rows,
    }


def render(data: dict) -> str:
    blob = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    return TEMPLATE.read_text(encoding='utf-8').replace('/*__DATA__*/null', blob)


def _load(path, default_name: str) -> dict:
    """`path` is the JSON file itself, or the DB it sits beside."""
    f = Path(path)
    f = f if f.name.endswith('.json') else f.with_name(default_name)
    return json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}


def load_translations(path) -> dict:
    return _load(path, TRANSLATIONS)


def load_photos(path) -> dict:
    return _load(path, PHOTOS)
