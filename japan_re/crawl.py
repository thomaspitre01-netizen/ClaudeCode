"""One crawl of one source: walk its search pages, read new or stale listings, record changes."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from . import db, records
from .fetch import Blocked, Disallowed, PoliteClient
from .sources import crawlable
from .sources.base import Source


def _stale(conn, url: str, refresh_days: float) -> bool:
    r = conn.execute('SELECT last_fetched FROM listings WHERE url = ?', (url,)).fetchone()
    if r is None or r['last_fetched'] is None:
        return True
    age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(r['last_fetched'])
    return age.total_seconds() > refresh_days * 86400


def crawl_source(conn, client: PoliteClient, source: Source, munis, categories=('detached_house', 'land'),
                 refresh_days: float = 3, max_details: int | None = None, log=print) -> dict:
    if not crawlable(source):
        raise PermissionError(f'{source.id} has policy {source.policy!r}; it is not crawled. '
                              f'See SOURCES.md.')
    started = db.now()
    run_id = conn.execute('INSERT INTO crawl_runs (source_id, started_at) VALUES (?,?)',
                          (source.id, started)).lastrowid
    conn.commit()
    stats = dict(pages=0, listings_seen=0, new_listings=0, price_changes=0, robots_blocked=0, errors=0)
    complete = True
    seen: set[str] = set()
    queue: list[tuple[str, str]] = []
    notes: list[str] = []

    targets = source.search_targets(munis, categories)

    try:
        for t in targets:
            url, pages = t.url, 0
            while url and pages < source.max_pages_per_target:
                try:
                    page = client.get(url)
                except Disallowed as e:
                    stats['robots_blocked'] += 1
                    notes.append(str(e))
                    log(f'  skipped: {e}')
                    complete = False
                    break
                if not page.ok:
                    stats['errors'] += 1
                    notes.append(f'HTTP {page.status} on {url}')
                    log(f'  HTTP {page.status} on {t.label}: {url}')
                    complete = False
                    break
                pages += 1
                stats['pages'] += 1
                links = source.detail_links(page.html, page.url)
                at = db.now()
                for link in links:
                    if link in seen:
                        continue
                    seen.add(link)
                    db.mark_seen(conn, link, at)
                    if _stale(conn, link, refresh_days):
                        queue.append((link, t.category_hint))
                conn.commit()
                skipped = getattr(source, 'skipped', None)
                log(f'  {t.label}: page {pages}, {len(links)} listings'
                    + (f' (skipped {", ".join(f"{n} {k}" for k, n in skipped.items())})' if skipped else ''))
                url = source.next_page(page.html, page.url)
            if url and pages >= source.max_pages_per_target:
                complete = False
                notes.append(f'page budget reached on {t.label}')

        stats['listings_seen'] = len(seen)
        if max_details is not None and len(queue) > max_details:
            queue = queue[:max_details]
            complete = False
            notes.append(f'--max-details {max_details} reached')

        for i, (link, cat) in enumerate(queue, 1):
            try:
                main = client.get(link)
            except Disallowed:
                stats['robots_blocked'] += 1
                continue
            if not main.ok:
                stats['errors'] += 1
                continue
            pages = [(main.url, main.html)]
            for extra in source.extra_pages(link):
                try:
                    ep = client.get(extra)
                    if ep.ok:
                        pages.append((ep.url, ep.html))
                except Disallowed:
                    stats['robots_blocked'] += 1
            pages[0] = (link, pages[0][1])   # keep the canonical URL as the identity
            row, stations = records.build(source.parse_detail(pages, cat))
            _, outcome = db.upsert_listing(conn, row, stations, raw_path=main.raw_path)
            stats['new_listings'] += outcome == 'new'
            stats['price_changes'] += outcome == 'price_change'
            conn.commit()
            if i % 10 == 0 or i == len(queue):
                log(f'  details {i}/{len(queue)} ({stats["new_listings"]} new, {stats["price_changes"]} price changes)')
    except Blocked as e:
        # The site refused us. Stop here; never retry around a block.
        complete = False
        stats['errors'] += 1
        notes.append(str(e))
        log(f'  stopped: {e}')

    stats["listings_seen"] = len(seen)
    munis_covered = {m.name_en for m in munis} if source.per_municipality else None
    removed = db.close_run(conn, source.id, complete, seen, munis_covered)
    conn.execute('''UPDATE crawl_runs SET finished_at=?, complete=?, pages=?, listings_seen=?, new_listings=?,
                    price_changes=?, robots_blocked=?, errors=?, notes=? WHERE id=?''',
                 (db.now(), int(complete), stats['pages'], stats['listings_seen'], stats['new_listings'],
                  stats['price_changes'], stats['robots_blocked'], stats['errors'],
                  '\n'.join(notes) or None, run_id))
    conn.commit()
    stats.update(complete=complete, removed=removed)
    return stats


def import_files(conn, source: Source, paths: list[Path], url_for=None, category: str | None = None) -> dict:
    """Parse pages saved from a browser (File > Save Page As). For sources that cannot
    be crawled from where this runs, or to test a parser on a real page.
    The listing URL is read from the page's canonical/og:url tag when present."""
    import re
    counts = {'new': 0, 'price_change': 0, 'changed': 0, 'unchanged': 0, 'skipped': 0}
    for p in paths:
        html = p.read_text(encoding='utf-8', errors='replace')
        url = url_for(p) if url_for else None
        if not url:
            m = (re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', html)
                 or re.search(r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)', html))
            url = m.group(1) if m else None
        if not url:
            print(f'{p}: skipped, no canonical/og:url in the page; pass --url')
            counts['skipped'] += 1
            continue
        url = source.canonical_url(url)
        row, stations = records.build(source.parse_detail([(url, html)], category))
        _, outcome = db.upsert_listing(conn, row, stations, raw_path=str(p))
        counts[outcome] += 1
    conn.commit()
    return counts
