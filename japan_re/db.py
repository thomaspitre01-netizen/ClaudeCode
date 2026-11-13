"""SQLite access: schema setup, listing upserts, and the change history."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

from . import sources

SCHEMA = Path(__file__).with_name('schema.sql')
DEFAULT_DB = Path('data/japan_re.sqlite')
REMOVE_AFTER_MISSED_RUNS = 2     # a listing absent from 2 complete crawls is 'removed'

# Columns a re-parse may overwrite. Identity and history columns are managed here.
_MANAGED = {'id', 'first_seen', 'last_seen', 'status', 'missed_runs', 'property_id',
            'last_fetched', 'description_en', 'title_en', 'translated_by', 'translated_at'}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.executescript(SCHEMA.read_text(encoding='utf-8'))
    sync_sources(conn)
    return conn


def sync_sources(conn: sqlite3.Connection):
    for s in sources.REGISTRY.values():
        conn.execute(
            '''INSERT INTO sources (id, name, base_url, kind, policy, policy_notes, enabled)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, base_url=excluded.base_url,
                 kind=excluded.kind, policy=excluded.policy, policy_notes=excluded.policy_notes''',
            (s.id, s.name, s.base_url, s.kind, s.policy, s.policy_notes,
             int(s.enabled_by_default and sources.crawlable(s))))
    # A policy downgrade always disables, whatever the stored flag said.
    conn.execute(f'''UPDATE sources SET enabled = 0
                     WHERE policy NOT IN ({",".join("?" * len(sources.CRAWLABLE))})''',
                 sources.CRAWLABLE)
    conn.commit()


def listing_columns(conn) -> list[str]:
    return [r['name'] for r in conn.execute('PRAGMA table_info(listings)')]


def event(conn, listing_id: int, kind: str, at: str, **detail):
    conn.execute('INSERT INTO listing_events (listing_id, observed_at, event_type, detail_json) '
                 'VALUES (?,?,?,?)', (listing_id, at, kind, json.dumps(detail, ensure_ascii=False)))


def upsert_listing(conn, row: dict, stations: list[dict], at: str | None = None,
                   raw_path: str | None = None) -> tuple[int, str]:
    """Insert or update a parsed listing. Returns (listing id, what happened):
    'new' | 'price_change' | 'changed' | 'unchanged'. Records price history and events."""
    at = at or now()
    cols = [c for c in listing_columns(conn) if c not in _MANAGED and c in row]
    old = conn.execute('SELECT * FROM listings WHERE url = ?', (row['url'],)).fetchone()

    if old is None:
        names = cols + ['first_seen', 'last_seen', 'last_fetched']
        conn.execute(f'INSERT INTO listings ({",".join(names)}) VALUES ({",".join("?" * len(names))})',
                     [row[c] for c in cols] + [at, at, at])
        lid = conn.execute('SELECT id FROM listings WHERE url = ?', (row['url'],)).fetchone()['id']
        if row.get('price_jpy') is not None:
            conn.execute('INSERT INTO price_history (listing_id, observed_at, price_jpy) VALUES (?,?,?)',
                         (lid, at, row['price_jpy']))
        event(conn, lid, 'new', at, price_jpy=row.get('price_jpy'))
        outcome = 'new'
    else:
        lid = old['id']
        outcome = 'unchanged' if old['content_hash'] == row.get('content_hash') else 'changed'
        if row.get('price_jpy') is not None and old['price_jpy'] != row['price_jpy']:
            conn.execute('INSERT INTO price_history (listing_id, observed_at, price_jpy, previous_price_jpy) '
                         'VALUES (?,?,?,?)', (lid, at, row['price_jpy'], old['price_jpy']))
            event(conn, lid, 'price_change', at, old=old['price_jpy'], new=row['price_jpy'])
            outcome = 'price_change'
        if old['agency_name'] and row.get('agency_name') and old['agency_name'] != row['agency_name']:
            event(conn, lid, 'agency_change', at, old=old['agency_name'], new=row['agency_name'])
        if old['status'] == 'removed':
            event(conn, lid, 'relisted', at)
        if outcome != 'unchanged':
            # A changed Japanese text needs a fresh translation.
            clear = ', description_en = NULL, translated_at = NULL' \
                if old['description_ja'] != row.get('description_ja') else ''
            conn.execute(f'UPDATE listings SET {", ".join(f"{c} = ?" for c in cols)}{clear} WHERE id = ?',
                         [row[c] for c in cols] + [lid])
        conn.execute("UPDATE listings SET last_seen = ?, last_fetched = ?, status = 'active', "
                     'missed_runs = 0 WHERE id = ?', (at, at, lid))

    conn.execute('DELETE FROM listing_stations WHERE listing_id = ?', (lid,))
    for s in stations:
        conn.execute('INSERT INTO listing_stations (listing_id, line_ja, line_en, station_ja, station_en, '
                     'walk_min, bus_min, raw_ja) VALUES (?,?,?,?,?,?,?,?)',
                     (lid, s['line_ja'], s['line_en'], s['station_ja'], s['station_en'],
                      s['walk_min'], s['bus_min'], s['raw_ja']))
    conn.execute('INSERT INTO snapshots (listing_id, url, fetched_at, http_status, content_hash, raw_path) '
                 'VALUES (?,?,?,?,?,?)', (lid, row['url'], at, 200, row.get('content_hash'), raw_path))
    ensure_property(conn, lid, at)
    return lid, outcome


def ensure_property(conn, listing_id: int, at: str):
    """Every listing belongs to a property; dedup later merges properties."""
    r = conn.execute('SELECT property_id FROM listings WHERE id = ?', (listing_id,)).fetchone()
    if r['property_id'] is None:
        cur = conn.execute('INSERT INTO properties (created_at, updated_at) VALUES (?,?)', (at, at))
        conn.execute('UPDATE listings SET property_id = ? WHERE id = ?', (cur.lastrowid, listing_id))


def mark_seen(conn, url: str, at: str) -> bool:
    """A list page showed this URL again. Returns False if we have never parsed it."""
    cur = conn.execute("UPDATE listings SET last_seen = ?, missed_runs = 0 WHERE url = ?", (at, url))
    row = conn.execute('SELECT id, status FROM listings WHERE url = ?', (url,)).fetchone()
    if row and row['status'] == 'removed':
        conn.execute("UPDATE listings SET status = 'active' WHERE id = ?", (row['id'],))
        event(conn, row['id'], 'relisted', at)
    return cur.rowcount > 0


def close_run(conn, source_id: str, complete: bool, seen_urls: set[str],
              municipalities: set[str] | None = None) -> int:
    """After a complete crawl of a source, listings it did not show count a missed run;
    after REMOVE_AFTER_MISSED_RUNS they are marked removed. Returns how many were removed.
    Incomplete runs (errors, blocks, --limit) never remove anything, and only listings
    in the municipalities this run searched are considered (None = the whole source)."""
    if not complete:
        return 0
    at = now()
    removed = 0
    for r in conn.execute("SELECT id, url, missed_runs, municipality FROM listings "
                          "WHERE source_id = ? AND status = 'active'", (source_id,)).fetchall():
        if r['url'] in seen_urls:
            continue
        if municipalities is not None and r['municipality'] not in municipalities:
            continue
        missed = r['missed_runs'] + 1
        if missed >= REMOVE_AFTER_MISSED_RUNS:
            conn.execute("UPDATE listings SET status = 'removed', missed_runs = ? WHERE id = ?", (missed, r['id']))
            event(conn, r['id'], 'removed', at)
            removed += 1
        else:
            conn.execute('UPDATE listings SET missed_runs = ? WHERE id = ?', (missed, r['id']))
    return removed
