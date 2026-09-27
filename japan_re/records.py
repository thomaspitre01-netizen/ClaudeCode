"""ParsedListing (raw Japanese label/value pairs) -> a row for the listings table."""
from __future__ import annotations

import hashlib
import json
import re

from . import areas
from . import normalize as n
from .sources.base import ParsedListing

# Label spellings seen across portals and agency sites. First match wins, exact
# label before prefix match, so '価格' does not swallow '価格改定日'.
LABELS = {
    'price':      ('価格', '販売価格', '売買価格', '価格(税込)', '物件価格', '売出価格'),
    'address':    ('所在地', '住所', '物件所在地', '所在', '住居表示'),
    'stations':   ('交通', '沿線・駅', '最寄駅', '最寄り駅', 'アクセス', '沿線'),
    'land':       ('土地面積', '敷地面積', '地積', '土地面積(公簿)', '土地'),
    'building':   ('建物面積', '延床面積', '延べ床面積', '専有面積', '延床面積(合計)'),
    'layout':     ('間取り', '間取'),
    'built':      ('築年月', '完成時期(築年月)', '建築年月', '築年', '竣工年月', '完成時期', '築年数'),
    'structure':  ('構造', '構造・工法', '建物構造', '構造・階建て', '構造・階建', '建物の構造'),
    'ratios':     ('建ぺい率・容積率', '建蔽率・容積率', '建ぺい率/容積率'),
    'coverage':   ('建ぺい率', '建蔽率'),
    'far':        ('容積率',),
    'zoning':     ('用途地域',),
    'road':       ('接道状況', '接道', '前面道路', '道路', '接道条件', '私道負担・道路'),
    'rights':     ('土地権利', '権利形態', '土地の権利形態', '土地権利形態', '権利'),
    'shape':      ('地勢', '土地形状', '形状', '地形'),
    'planning':   ('都市計画',),
    'restrict':   ('法令上の制限', 'その他制限事項', '制限事項', 'その他の法令上の制限'),
    'occupancy':  ('現況',),
    'handover':   ('引渡し', '引渡可能時期', '引渡し時期', '引渡時期', '入居時期'),
    'agency':     ('会社名', '取扱会社', '情報提供会社', '問合せ先', '問い合わせ先', '商号', '取扱店舗', '会社概要'),
    'license':    ('免許番号', '宅建業免許', '宅地建物取引業免許'),
    'phone':      ('電話番号', 'TEL', '電話'),
    'mgmt':       ('管理費',),
    'repair':     ('修繕積立金',),
    'costs':      ('諸費用', 'その他費用', 'その他一時金', '私道負担・道路'),
    'type':       ('物件種目', '種目', '物件種別', '種別'),
}


def pick(pairs: dict[str, str], key: str) -> str | None:
    names = LABELS[key]
    for name in names:
        if name in pairs:
            return pairs[name]
    for name in names:
        for label, value in pairs.items():
            if label.startswith(name) and len(label) <= len(name) + 6:
                return value
    return None


def build(p: ParsedListing) -> tuple[dict, list[dict]]:
    """Returns (listing columns, station rows)."""
    g = lambda k: pick(p.pairs, k)  # noqa: E731
    row: dict = {'source_id': p.source_id, 'source_listing_id': p.source_listing_id, 'url': p.url,
                 'title_ja': p.title, 'description_ja': p.description}

    row['price_jpy'], row['price_note_ja'] = n.parse_price(g('price'))
    row['management_fee_jpy'] = n.parse_monthly_fee(g('mgmt'))
    row['repair_reserve_jpy'] = n.parse_monthly_fee(g('repair'))
    row['other_costs_ja'] = g('costs')

    row['address_ja'] = g('address')
    row.update(n.split_address(row['address_ja']))

    row['land_area_m2'], row['land_area_note_ja'] = n.parse_area(g('land'))
    row['building_area_m2'], _ = n.parse_area(g('building'))
    row['plot_shape_ja'] = g('shape')
    row['road_access_ja'] = g('road')
    row['road_width_m'], row['frontage_m'] = n.parse_road(row['road_access_ja'])

    cov, far = n.parse_coverage_ratios(g('ratios'))
    row['building_coverage_pct'] = cov if cov is not None else n.parse_percent(g('coverage'))
    row['floor_area_ratio_pct'] = far if far is not None else n.parse_percent(g('far'))
    row['zoning_ja'], row['zoning'] = n.parse_zoning(g('zoning'))
    row['land_rights_ja'] = g('rights')
    row['land_rights'], row['is_freehold'] = n.parse_land_rights(row['land_rights_ja'])
    row['restrictions_ja'] = ' / '.join(x for x in (g('planning'), g('restrict')) if x) or None

    row['year_built'], row['month_built'] = n.parse_year_month(g('built'))
    row['structure_ja'] = g('structure')
    row['structure'], row['floors_above'], row['floors_below'] = n.parse_structure(row['structure_ja'])
    row['layout_ja'], row['rooms'] = n.parse_layout(g('layout'))
    lay = row['layout_ja'] or ''
    row['kitchens'] = (2 if re.search(r'二世帯|2世帯|キッチン2', p.description or '') else
                       1 if re.search(r'K', lay) else None)
    row['bathrooms'] = 2 if re.search(r'浴室2|バス2|2ヶ所の浴室', p.description or '') else None

    row['occupancy'] = n.parse_occupancy(g('occupancy'))
    row['handover_ja'] = g('handover')

    texts = (p.title, p.description, g('type'), g('occupancy'), g('restrict'), g('costs'),
             ' '.join(p.pairs.values()))
    row['property_type'], row['property_type_evidence'] = n.classify_type(
        p.category_hint, ' '.join(x for x in (p.title, g('type')) if x), p.description)
    row['property_type_ja'] = g('type')
    if row['property_type'] == 'condominium' and row['land_area_m2']:
        # a flat's 敷地面積 is the whole block's site, not land the buyer gets
        row['land_area_note_ja'] = f"敷地全体 {row['land_area_m2']}m2"
        row['land_area_m2'] = None
    row['condition'], row['condition_evidence'] = n.classify_condition(row['year_built'], *texts)
    if row['property_type'] == 'land' and row['condition'] == 'unknown' and not row['building_area_m2']:
        row['condition'] = None   # bare land: renovation does not apply
    row['earthquake_standard'] = n.earthquake_standard(row['year_built'], row['month_built'],
                                                       ' '.join(t for t in texts if t))
    row.update(n.flags(*texts))

    agency = g('agency')
    row['agency_name'] = agency.split(' ')[0][:80] if agency else None
    lic = re.search(r'(?:国土交通大臣|\S{2,3}[都道府県]知事)\s*\(\d+\)\s*第\s*\d+\s*号',
                    ' '.join(x for x in (g('license'), agency) if x))
    row['agency_license'] = lic.group(0) if lic else g('license')
    row['agency_phone'] = g('phone')

    row['lat'], row['lng'] = p.lat, p.lng
    row['geocode_source'] = 'page' if p.lat else None
    row['geocode_precision'] = 'exact' if p.lat else None
    row['thumbnail_url'] = p.images[0] if p.images else None
    row['image_urls_json'] = json.dumps(p.images, ensure_ascii=False) if p.images else None
    row['raw_fields_json'] = json.dumps(p.pairs, ensure_ascii=False)
    row['content_hash'] = hashlib.sha1(
        (row['raw_fields_json'] + (p.description or '')).encode()).hexdigest()

    in_area = row['municipality'] is not None
    under_cap = row['price_jpy'] is None or row['price_jpy'] <= areas.PRICE_CAP_JPY
    row['in_scope'] = int(in_area and under_cap)

    stations = n.parse_stations(g('stations'))
    return row, stations
