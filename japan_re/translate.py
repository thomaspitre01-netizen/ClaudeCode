"""English for every listing, with the Japanese always kept alongside.

Two layers:
  * structured fields are translated deterministically by normalize.py (zoning,
    structure, station names, property type). No model involved, nothing lost.
  * free text (title, description) is translated by Claude when ANTHROPIC_API_KEY
    is set. Translations are cached by the hash of the Japanese text, so an
    unchanged description is never paid for twice.

`summary_en` builds the one-line English digest the brief asks for:
  ¥48M · 310 m² land · 140 m² house · 1975 · 8 min to Kita-Kamakura · ¥155k/m² land
"""
from __future__ import annotations

import hashlib
import os

from . import db

MODEL = os.environ.get('JRE_TRANSLATE_MODEL', 'claude-opus-5')

SYSTEM = """You translate Japanese real-estate listings into English for a private buyer.
Translate faithfully and completely; do not summarise, embellish or drop caveats.
Keep these as they are, with a short gloss in brackets the first time they appear:
legal and zoning terms (e.g. 再建築不可 [rebuilding not permitted], 市街化調整区域
[urbanization control area], 私道負担 [share of private road], セットバック [setback],
古家付き土地 [land with an old house]), and building names and place names in romaji.
Prices stay in yen exactly as written (4,980万円 -> ¥49.8M). Areas stay in m².
Return only the translation."""


def _yen_short(v: int | None) -> str | None:
    if v is None:
        return None
    if v >= 100_000_000:
        return f'¥{v / 100_000_000:.2f}億'.replace('.00億', '億') + f' (¥{v / 1e6:,.0f}M)'
    return f'¥{v / 1e6:,.1f}M'.replace('.0M', 'M')


TYPE_EN = {'detached_house': 'house', 'traditional_house': 'traditional house', 'kominka': 'kominka',
           'machiya': 'machiya', 'apartment': 'apartment', 'condominium': 'condo',
           'entire_building': 'whole building', 'land': 'land', 'mixed_use': 'mixed-use',
           'commercial': 'commercial', 'other': 'property'}
COND_EN = {'move_in_ready': 'move-in ready', 'minor_renovation': 'minor renovation',
           'major_renovation': 'major renovation', 'full_renovation': 'full renovation',
           'derelict_rebuild': 'derelict / rebuild'}


def summary_en(r) -> str:
    """One readable line from a v_properties or listings row."""
    r = dict(r)
    parts = [_yen_short(r.get('price_jpy'))]
    if r.get('municipality'):
        parts.append(r['municipality'])
    parts.append(TYPE_EN.get(r.get('property_type') or '', None))
    if r.get('land_area_m2'):
        parts.append(f'{r["land_area_m2"]:,.0f} m² land')
    if r.get('building_area_m2'):
        parts.append(f'{r["building_area_m2"]:,.0f} m² building')
    if r.get('year_built'):
        parts.append(f'built {r["year_built"]}')
    walk = r.get('station_walk_min')
    if walk is not None:
        st = r.get('nearest_station')
        parts.append(f'{walk} min walk' + (f' ({st.split(" / ")[-1]})' if st else ''))
    ppm = r.get('price_per_m2_land')
    if ppm is None and r.get('price_jpy') and r.get('land_area_m2'):
        ppm = r['price_jpy'] / r['land_area_m2']
    if ppm:
        parts.append(f'¥{ppm / 1000:,.0f}k/m² land')
    if r.get('condition') in COND_EN:
        parts.append(COND_EN[r['condition']])
    if r.get('rebuild_prohibited'):
        parts.append('rebuild not permitted')
    return ' · '.join(p for p in parts if p)


class Translator:
    def __init__(self, conn, model: str = MODEL):
        import anthropic  # optional dependency, only needed here
        self.client = anthropic.Anthropic()
        self.conn = conn
        self.model = model

    def translate(self, text: str) -> str | None:
        h = hashlib.sha256(text.encode()).hexdigest()
        hit = self.conn.execute('SELECT text_en FROM translation_cache WHERE text_hash = ?', (h,)).fetchone()
        if hit:
            return hit['text_en']
        # Server-side fallback: if a safety classifier declines, the request is retried
        # on another model instead of failing the whole batch.
        resp = self.client.beta.messages.create(
            model=self.model,
            max_tokens=8000,
            system=SYSTEM,
            messages=[{'role': 'user', 'content': text}],
            output_config={'effort': 'low'},
            betas=['server-side-fallback-2026-07-01'],
            fallbacks='default',
        )
        if resp.stop_reason == 'refusal':
            return None
        out = ''.join(b.text for b in resp.content if b.type == 'text').strip()
        if not out:
            return None
        self.conn.execute('INSERT OR REPLACE INTO translation_cache VALUES (?,?,?,?)',
                          (h, out, resp.model, db.now()))
        return out


def run(conn, limit: int | None = None, in_scope_only: bool = True, log=print) -> int:
    """Translate titles and descriptions that have no English yet."""
    if not (os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('ANTHROPIC_AUTH_TOKEN')):
        log('ANTHROPIC_API_KEY is not set: structured fields are already in English; '
            'free-text descriptions stay Japanese-only until a key is provided.')
        return 0
    t = Translator(conn)
    where = 'description_en IS NULL AND (description_ja IS NOT NULL OR title_ja IS NOT NULL)'
    if in_scope_only:
        where += " AND in_scope = 1 AND status = 'active'"
    rows = conn.execute(f'SELECT id, title_ja, description_ja FROM listings WHERE {where} '
                        f'ORDER BY first_seen DESC' + (f' LIMIT {int(limit)}' if limit else '')).fetchall()
    done = 0
    for r in rows:
        title = t.translate(r['title_ja']) if r['title_ja'] else None
        desc = t.translate(r['description_ja']) if r['description_ja'] else ''
        if desc is None:
            continue
        conn.execute('UPDATE listings SET title_en = ?, description_en = ?, translated_by = ?, '
                     'translated_at = ? WHERE id = ?', (title, desc, t.model, db.now(), r['id']))
        conn.commit()
        done += 1
        if done % 10 == 0:
            log(f'  translated {done}/{len(rows)}')
    return done
