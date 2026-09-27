"""The private dashboard: one self-contained HTML page (map, filters, results, Leads) built
from the database. Read-only: it never writes to the DB.

    python -m japan_re dashboard --out dashboard.html

The page embeds its data as JSON, so it works as a file or as a published Artifact. It can't
load map tiles or listing photos (the Artifact sandbox blocks other hosts), so the map is drawn
from the station areas themselves and each listing links out to its source.
"""
from __future__ import annotations

import datetime as dt
import json
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


def build(conn) -> dict:
    rows = conn.execute("SELECT * FROM v_properties WHERE status = 'active' AND in_scope = 1 "
                        'AND price_jpy IS NOT NULL AND price_jpy <= ?', (HARD_MAX,)).fetchall()
    props = []
    for row in rows:
        r = dict(row)
        area, tier, station = leads.locate(r, leads._stations(conn, r['property_id']))
        p = {k: r[k] for k in KEYS}
        p.update(area=area, tier=tier, main_station=station)
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
