"""Command line for the property database. Run `python -m japan_re --help`."""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from . import areas, db, dedup, sources
from .normalize import CONDITIONS, PROPERTY_TYPES


def _yen(s: str) -> int:
    """'50M', '5000万', '1.2億', '48000000' -> yen."""
    t = s.strip().replace(',', '').replace('¥', '')
    m = re.fullmatch(r'([\d.]+)\s*(m|M|万|億|k|K)?', t)
    if not m:
        raise argparse.ArgumentTypeError(f'not a price: {s}')
    mult = {'m': 1e6, 'M': 1e6, '万': 1e4, '億': 1e8, 'k': 1e3, 'K': 1e3, None: 1}[m.group(2)]
    return int(float(m.group(1)) * mult)


# ---------------------------------------------------------------- commands

def cmd_sources(conn, a):
    for r in conn.execute('SELECT * FROM sources ORDER BY enabled DESC, kind, id'):
        state = 'ON ' if r['enabled'] else 'off'
        print(f'{state} {r["id"]:<14} {r["policy"]:<18} {r["kind"]:<11} {r["name"]}')
        if a.verbose:
            print(f'      {r["policy_notes"]}')


def cmd_crawl(conn, a):
    from .crawl import crawl_source
    from .fetch import PoliteClient
    munis = areas.select(a.tier, a.area)
    if not munis:
        sys.exit('no municipalities match --area/--tier')
    if a.source:
        chosen = [sources.get(s) for s in a.source]
    else:
        enabled = {r['id'] for r in conn.execute('SELECT id FROM sources WHERE enabled = 1')}
        chosen = [s for s in sources.REGISTRY.values() if s.id in enabled]
    client = PoliteClient(contact=a.contact)
    for s in chosen:
        if not sources.crawlable(s):
            print(f'{s.id}: skipped, policy is {s.policy!r} (see SOURCES.md)')
            continue
        print(f'{s.id}: crawling {len(munis)} municipalities')
        try:
            stats = crawl_source(conn, client, s, munis, tuple(a.categories), a.refresh_days,
                                 a.max_details)
        except Exception as e:  # one broken source must not stop the others
            print(f'{s.id}: failed: {e}')
            continue
        print(f'{s.id}: {stats}')
    print('dedup:', dedup.run(conn))


def cmd_import(conn, a):
    from .crawl import import_files
    src = sources.get(a.source)
    paths = [Path(p) for p in a.files]
    if a.url and len(paths) != 1:
        sys.exit('--url works with a single file')
    print(import_files(conn, src, paths, url_for=(lambda _: a.url) if a.url else None,
                       category=a.category))
    print('dedup:', dedup.run(conn))


def cmd_dedup(conn, a):
    print(dedup.run(conn))


def cmd_unmerge(conn, a):
    """Split a wrongly merged listing into its own property and never re-merge it."""
    r = conn.execute('SELECT id, property_id FROM listings WHERE id = ?', (a.listing_id,)).fetchone()
    if not r:
        sys.exit('no such listing')
    others = [x['id'] for x in conn.execute('SELECT id FROM listings WHERE property_id = ? AND id != ?',
                                            (r['property_id'], r['id']))]
    for o in others:
        lo, hi = sorted((r['id'], o))
        conn.execute('''INSERT INTO dedup_matches (listing_a, listing_b, score, reasons_json, decision)
                        VALUES (?,?,0,'["split by hand"]','rejected')
                        ON CONFLICT(listing_a, listing_b) DO UPDATE SET decision='rejected' ''', (lo, hi))
    conn.execute('UPDATE listings SET property_id = NULL WHERE id = ?', (r['id'],))
    db.ensure_property(conn, r['id'], db.now())
    conn.commit()
    print(f'listing {r["id"]} split from {len(others)} others')


def cmd_geocode(conn, a):
    from . import geocode
    geocode.run(conn, limit=a.limit)


def cmd_translate(conn, a):
    from . import translate
    print(f'translated {translate.run(conn, limit=a.limit)} listings')


def cmd_stats(conn, a):
    q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    base = "FROM v_properties WHERE status = 'active' AND in_scope = 1"
    rows = [
        ('Properties currently tracked', q(f'SELECT COUNT(*) {base}')),
        ('New this week', q(f"SELECT COUNT(*) {base} AND first_seen >= datetime('now', '-7 days')")),
        ('Under ¥50M', q(f'SELECT COUNT(*) {base} AND price_jpy < 50000000')),
        ('Traditional / kominka / machiya',
         q(f"SELECT COUNT(*) {base} AND property_type IN ('traditional_house','kominka','machiya')")),
        ('Large plots (200 m²+)', q(f'SELECT COUNT(*) {base} AND land_area_m2 >= 200')),
        ('Major / full renovation or rebuild',
         q(f"SELECT COUNT(*) {base} AND condition IN ('major_renovation','full_renovation','derelict_rebuild')")),
        ('Price cuts in the last 30 days',
         q("SELECT COUNT(*) FROM listing_events WHERE event_type = 'price_change' "
           "AND observed_at >= datetime('now', '-30 days')")),
        ('Favorites', q('SELECT COUNT(*) FROM favorites')),
        ('Listings (all sources, before dedup)', q('SELECT COUNT(*) FROM listings')),
    ]
    for label, v in rows:
        print(f'{label:<40} {v:>8,}')
    print('\nBy source:')
    for r in conn.execute("SELECT source_id, COUNT(*) n, SUM(status='active') act FROM listings GROUP BY 1"):
        print(f'  {r["source_id"]:<14} {r["n"]:>6} listings, {r["act"]} active')


def _search_sql(a) -> tuple[str, list]:
    where, args = ["status = 'active'"], []
    if not a.all:
        where.append('in_scope = 1')
    for col, op, val in (('price_jpy', '>=', a.min_price), ('price_jpy', '<=', a.max_price),
                         ('land_area_m2', '>=', a.min_land), ('land_area_m2', '<=', a.max_land),
                         ('building_area_m2', '>=', a.min_building), ('building_area_m2', '<=', a.max_building),
                         ('year_built', '>=', a.built_after), ('year_built', '<=', a.built_before),
                         ('station_walk_min', '<=', a.walk)):
        if val is not None:
            where.append(f'{col} {op} ?')
            args.append(val)
    for col, vals in (('property_type', a.type), ('condition', a.condition)):
        if vals:
            where.append(f'{col} IN ({",".join("?" * len(vals))})')
            args += vals
    if a.area:
        where.append(f'(municipality IN ({",".join("?" * len(a.area))}) OR municipality_ja IN '
                     f'({",".join("?" * len(a.area))}))')
        args += a.area + a.area
    if a.station:
        where.append('property_id IN (SELECT l.property_id FROM listings l JOIN listing_stations s '
                     'ON s.listing_id = l.id WHERE s.station_en = ? OR s.station_ja = ? OR s.line_en LIKE ?)')
        args += [a.station, a.station, f'%{a.station}%']
    if a.favorites:
        where.append('is_favorite = 1')
    order = {'price': 'price_jpy', 'land': 'land_area_m2 DESC', 'new': 'first_seen DESC',
             'ppm': 'price_per_m2_land'}[a.sort]
    return f'SELECT * FROM v_properties WHERE {" AND ".join(where)} ORDER BY {order} NULLS LAST', args


def cmd_search(conn, a):
    from .translate import summary_en
    sql, args = _search_sql(a)
    rows = conn.execute(sql + f' LIMIT {int(a.limit)}', args).fetchall()
    for r in rows:
        fav = '♥' if r['is_favorite'] else ' '
        print(f'{fav} #{r["property_id"]:<6} {summary_en(r)}')
        print(f'          {r["primary_url"]}  [{r["sources"]}]')
    print(f'{len(rows)} shown')


def cmd_show(conn, a):
    from .translate import summary_en
    p = conn.execute('SELECT * FROM v_properties WHERE property_id = ?', (a.property_id,)).fetchone()
    if not p:
        sys.exit('no such property')
    print(summary_en(p))
    skip = {'title_ja', 'title_en'}
    for k in p.keys():
        if p[k] is not None and k not in skip:
            print(f'  {k:<26} {p[k]}')
    print('\nListings:')
    for l in conn.execute('SELECT * FROM listings WHERE property_id = ? ORDER BY first_seen', (a.property_id,)):
        print(f'  [{l["source_id"]}] {l["status"]:<8} {l["url"]}  first {l["first_seen"][:10]} '
              f'last {l["last_seen"][:10]}  agency {l["agency_name"]}')
    print('\nPrice history:')
    for h in conn.execute('SELECT ph.*, l.source_id FROM price_history ph JOIN listings l ON l.id = ph.listing_id '
                          'WHERE l.property_id = ? ORDER BY observed_at', (a.property_id,)):
        prev = f' (was ¥{h["previous_price_jpy"]:,})' if h['previous_price_jpy'] else ''
        print(f'  {h["observed_at"][:10]}  ¥{h["price_jpy"]:,}{prev}  [{h["source_id"]}]')
    l = conn.execute('SELECT title_ja, title_en, description_ja, description_en FROM listings '
                     'WHERE property_id = ? ORDER BY length(description_ja) DESC LIMIT 1',
                     (a.property_id,)).fetchone()
    print('\nTitle:', l['title_ja'], '/', l['title_en'] or '(not translated)')
    print('\nDescription (English):\n', l['description_en'] or '(not translated yet)')
    print('\n原文 (Japanese):\n', l['description_ja'])


def cmd_fav(conn, a):
    if a.action == 'add':
        conn.execute('INSERT OR REPLACE INTO favorites VALUES (?,?,?)', (a.property_id, db.now(), a.note))
    elif a.action == 'remove':
        conn.execute('DELETE FROM favorites WHERE property_id = ?', (a.property_id,))
    conn.commit()
    from .translate import summary_en
    for r in conn.execute('SELECT v.*, f.note FROM favorites f JOIN v_properties v '
                          'ON v.property_id = f.property_id ORDER BY f.added_at DESC'):
        print(f'♥ #{r["property_id"]:<6} {r["status"]:<8} {summary_en(r)}  '
              f'[{r["sources"]}, found {r["first_seen"][:10]}]' + (f'  - {r["note"]}' if r['note'] else ''))


def cmd_reno(conn, a):
    conn.execute('UPDATE properties SET renovation_low_jpy = ?, renovation_high_jpy = ?, '
                 'renovation_notes = COALESCE(?, renovation_notes), updated_at = ? WHERE id = ?',
                 (a.low, a.high, a.note, db.now(), a.property_id))
    conn.commit()
    r = conn.execute('SELECT price_jpy, est_acquisition_cost_jpy FROM v_properties WHERE property_id = ?',
                     (a.property_id,)).fetchone()
    if r and r['price_jpy']:
        acq = r['est_acquisition_cost_jpy']
        print(f'Purchase ¥{r["price_jpy"] / 1e6:,.1f}M (≈¥{acq / 1e6:,.1f}M with purchase costs) + '
              f'renovation ¥{a.low / 1e6:,.0f}–{a.high / 1e6:,.0f}M = '
              f'total project ¥{(acq + a.low) / 1e6:,.0f}–{(acq + a.high) / 1e6:,.0f}M')


def cmd_events(conn, a):
    """Recent changes: what an alert would have said."""
    for e in conn.execute('''SELECT e.*, l.property_id, l.municipality FROM listing_events e
                             JOIN listings l ON l.id = e.listing_id
                             WHERE e.observed_at >= datetime('now', ?) AND l.in_scope = 1
                             AND e.event_type IN ('new','price_change','removed','relisted')
                             ORDER BY e.observed_at DESC LIMIT ?''', (f'-{a.days} days', a.limit)):
        d = json.loads(e['detail_json'] or '{}')
        extra = (f'¥{d["old"]:,} -> ¥{d["new"]:,}' if e['event_type'] == 'price_change'
                 else f'¥{d["price_jpy"]:,}' if d.get('price_jpy') else '')
        print(f'{e["observed_at"][:10]} {e["event_type"]:<13} #{e["property_id"]:<6} {e["municipality"]:<12} {extra}')


def cmd_mark(conn, a):
    """Record that a property was checked: seen, liked (also a favorite) or passed."""
    if a.state == 'clear':
        conn.execute('DELETE FROM reviews WHERE property_id IN (%s)' % ','.join('?' * len(a.property_id)),
                     a.property_id)
    for pid in a.property_id if a.state != 'clear' else ():
        conn.execute('INSERT OR REPLACE INTO reviews VALUES (?,?,?,?)', (pid, a.state, db.now(), a.note))
        if a.state == 'liked':
            conn.execute('INSERT OR IGNORE INTO favorites VALUES (?,?,?)', (pid, db.now(), a.note))
    conn.commit()
    for r in conn.execute('SELECT * FROM reviews ORDER BY reviewed_at DESC LIMIT 20'):
        print(f'#{r["property_id"]:<6} {r["state"]:<7} {r["reviewed_at"][:10]}  {r["note"] or ""}')


def cmd_leads(conn, a):
    from . import leads
    found = leads.find(conn, areas=a.area, include_secondary=not a.primary_only, max_price=a.max_price,
                       include_passed=a.show_passed)
    if a.unchecked:
        found = [L for L in found if not L.review]
    if not a.watchlist:
        found = [L for L in found if L.is_lead or a.out]
    if a.out:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        if a.format == 'json':
            out.write_text(json.dumps(leads.to_json(found), ensure_ascii=False, indent=1), encoding='utf-8')
        else:
            out.write_text(leads.to_markdown(found), encoding='utf-8')
        print(f'{sum(L.is_lead for L in found)} leads, {sum(not L.is_lead for L in found)} watchlist -> {out}')
        return
    for L in found[:a.limit]:
        r = L.row
        dots = ''.join(d for d, _ in L.indicators.values())
        tag = ('' if L.is_lead else ' [watchlist]') + (f' [{L.review}]' if L.review else '')
        print(f'#{r["property_id"]:<6} {dots} {", ".join(L.categories)}{tag}')
        print(f'        {L.reason}')
        print(f'        {r["primary_url"]}')
    print(f'{sum(L.is_lead for L in found)} leads')


def cmd_export(conn, a):
    rows = conn.execute("SELECT * FROM v_properties" + ('' if a.all else ' WHERE in_scope = 1')).fetchall()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if a.format == 'json':
        out.write_text(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=1), encoding='utf-8')
    else:
        with out.open('w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            if rows:
                w.writerow(rows[0].keys())
            w.writerows([tuple(r) for r in rows])
    print(f'{len(rows)} properties -> {out}')


# ---------------------------------------------------------------- parser

def main(argv=None):
    ap = argparse.ArgumentParser(prog='japan_re', description=__doc__)
    ap.add_argument('--db', default=str(db.DEFAULT_DB))
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('sources', help='list sources, their policy and whether they are crawled')
    p.add_argument('-v', '--verbose', action='store_true')
    p.set_defaults(fn=cmd_sources)

    p = sub.add_parser('crawl', help='crawl enabled sources (or --source X)')
    p.add_argument('--source', action='append')
    p.add_argument('--tier', choices=areas.TIERS, default='core')
    p.add_argument('--area', action='append', help='municipality, English or Japanese (repeatable)')
    p.add_argument('--categories', nargs='+', default=['detached_house', 'land'],
                   choices=['detached_house', 'land', 'condominium'])
    p.add_argument('--refresh-days', type=float, default=3, help='re-read a listing page after this many days')
    p.add_argument('--max-details', type=int, help='stop after reading this many listing pages')
    p.add_argument('--contact', help='email for the User-Agent (or set JRE_CONTACT)')
    p.set_defaults(fn=cmd_crawl)

    p = sub.add_parser('import-html', help='parse listing pages saved from a browser')
    p.add_argument('--source', required=True, choices=list(sources.REGISTRY))
    p.add_argument('--category', choices=PROPERTY_TYPES)
    p.add_argument('--url', help='the listing URL, when the saved page does not say')
    p.add_argument('files', nargs='+')
    p.set_defaults(fn=cmd_import)

    sub.add_parser('dedup', help='re-run duplicate detection').set_defaults(fn=cmd_dedup)
    p = sub.add_parser('unmerge', help='split a wrongly merged listing into its own property')
    p.add_argument('listing_id', type=int)
    p.set_defaults(fn=cmd_unmerge)

    p = sub.add_parser('geocode', help='coordinates from GSI for listings without them')
    p.add_argument('--limit', type=int)
    p.set_defaults(fn=cmd_geocode)

    p = sub.add_parser('translate', help='English titles/descriptions via Claude (needs ANTHROPIC_API_KEY)')
    p.add_argument('--limit', type=int)
    p.set_defaults(fn=cmd_translate)

    sub.add_parser('stats', help='headline numbers').set_defaults(fn=cmd_stats)

    p = sub.add_parser('search', help='filter properties')
    p.add_argument('--min-price', type=_yen)
    p.add_argument('--max-price', type=_yen)
    p.add_argument('--min-land', type=float)
    p.add_argument('--max-land', type=float)
    p.add_argument('--min-building', type=float)
    p.add_argument('--max-building', type=float)
    p.add_argument('--built-after', type=int)
    p.add_argument('--built-before', type=int)
    p.add_argument('--walk', type=int, help='max minutes on foot to a station')
    p.add_argument('--type', action='append', choices=PROPERTY_TYPES)
    p.add_argument('--condition', action='append', choices=CONDITIONS)
    p.add_argument('--area', action='append')
    p.add_argument('--station', help='station or line, e.g. Kichijoji or Chuo')
    p.add_argument('--favorites', action='store_true')
    p.add_argument('--all', action='store_true', help='include out-of-scope listings')
    p.add_argument('--sort', choices=['price', 'land', 'new', 'ppm'], default='new')
    p.add_argument('--limit', type=int, default=50)
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser('show', help='everything about one property')
    p.add_argument('property_id', type=int)
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser('fav', help='favorites: add / remove / list')
    p.add_argument('action', choices=['add', 'remove', 'list'])
    p.add_argument('property_id', type=int, nargs='?')
    p.add_argument('--note')
    p.set_defaults(fn=cmd_fav)

    p = sub.add_parser('reno', help='record a renovation estimate for a property')
    p.add_argument('property_id', type=int)
    p.add_argument('--low', type=_yen, required=True)
    p.add_argument('--high', type=_yen, required=True)
    p.add_argument('--note')
    p.set_defaults(fn=cmd_reno)

    p = sub.add_parser('events', help='recent new listings, price changes and removals')
    p.add_argument('--days', type=int, default=7)
    p.add_argument('--limit', type=int, default=100)
    p.set_defaults(fn=cmd_events)

    p = sub.add_parser('leads', help='the curated short list: ≤¥70M, land/age/character/renovation first')
    p.add_argument('--area', action='append', help='e.g. Kichijoji, Koenji, Kamakura, Zushi (repeatable)')
    p.add_argument('--primary-only', action='store_true', help='Kichijoji/Nakano/Koenji/Kamakura/Kita-Kamakura')
    p.add_argument('--max-price', type=_yen, default=70_000_000, help='capped at ¥70M')
    p.add_argument('--watchlist', action='store_true', help='also print watchlist entries')
    p.add_argument('--limit', type=int, default=60)
    p.add_argument('--out', help='write the whole Leads page (leads + watchlist) here')
    p.add_argument('--format', choices=['md', 'json'], default='md')
    p.add_argument('--unchecked', action='store_true', help='only leads not yet marked seen/liked/passed')
    p.add_argument('--show-passed', action='store_true', help='include the ones marked passed')
    p.set_defaults(fn=cmd_leads)

    p = sub.add_parser('mark', help='mark properties as seen, liked or passed (clear to undo)')
    p.add_argument('state', choices=['seen', 'liked', 'passed', 'clear'])
    p.add_argument('property_id', type=int, nargs='+')
    p.add_argument('--note')
    p.set_defaults(fn=cmd_mark)

    p = sub.add_parser('export', help='write v_properties to CSV or JSON')
    p.add_argument('--format', choices=['csv', 'json'], default='csv')
    p.add_argument('--out', default='data/export/properties.csv')
    p.add_argument('--all', action='store_true')
    p.set_defaults(fn=cmd_export)

    a = ap.parse_args(argv)
    if a.cmd == 'fav' and a.action != 'list' and a.property_id is None:
        ap.error('fav add/remove needs a property id')
    conn = db.connect(a.db)
    a.fn(conn, a)
