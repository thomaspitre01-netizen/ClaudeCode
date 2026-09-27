"""A few photos per lead, embedded in the dashboard as data: URIs (the published page
can't load images from other sites).

    python -m japan_re photos --out <dir>/photos.json

SUUMO: the listing page names its photos; SUUMO's own resizer serves them small
(img01.suumo.com/jj/resizeImage?...&w=480&h=360), so nothing is resized here. Other
sources: the stored image URLs, kept only when already small enough. Photos already
in the file are not fetched again. Everything goes through the polite client, so
robots.txt and blocks are respected; a blocked host is skipped, never worked around.
"""
from __future__ import annotations

import base64
import html
import json
import re
import urllib.parse
from pathlib import Path

import requests

from . import leads
from .fetch import Blocked, Disallowed, PoliteClient

PER_LEAD = 3
MAX_BYTES = 250_000
SUUMO_IMG = re.compile(r'https://img01\.suumo\.com/jj/resizeImage\?src=(gazo[^&"\'\s]+)')
SKIP = ('/global/', 'pagetop', 'logo', 'banner', 'bn_')


def suumo_photos(client: PoliteClient, url: str) -> list[str]:
    page = client.get(url)
    srcs = []
    for m in SUUMO_IMG.finditer(html.unescape(page.html) if page.ok else ''):
        if m.group(1) not in srcs:
            srcs.append(m.group(1))
    return [f'https://img01.suumo.com/jj/resizeImage?src={s}&w=480&h=360' for s in srcs[:PER_LEAD]]


def fetch_image(client: PoliteClient, url: str) -> str | None:
    host = urllib.parse.urlsplit(url).netloc
    if host in client._blocked or not client.allowed(url):
        return None
    client._wait(host, client.min_delay)
    try:
        r = client.session.get(url, timeout=client.timeout)
    except requests.RequestException:
        return None
    if r.status_code == 403:
        client._blocked.add(host)
        return None
    kind = r.headers.get('content-type', '').split(';')[0]
    if r.status_code != 200 or not kind.startswith('image/') or len(r.content) > MAX_BYTES:
        return None
    return f'data:{kind};base64,{base64.b64encode(r.content).decode()}'


def collect(conn, out: Path, client: PoliteClient | None = None) -> dict:
    client = client or PoliteClient()
    photos = json.loads(out.read_text()) if out.exists() else {}
    for L in leads.find(conn):
        pid = str(L.row['property_id'])
        if not L.is_lead or photos.get(pid):
            continue
        urls = []
        for source, url, images in conn.execute(
                "SELECT source_id, url, image_urls_json FROM listings WHERE property_id = ? "
                "ORDER BY source_id = 'suumo'", (L.row['property_id'],)):
            if source == 'suumo':
                try:
                    urls += suumo_photos(client, url)
                except (Blocked, Disallowed):
                    pass
            else:
                urls += [u for u in json.loads(images or '[]') if not any(s in u for s in SKIP)]
            if len(urls) >= PER_LEAD:
                break
        got = [d for d in (fetch_image(client, u) for u in urls[:PER_LEAD * 2]) if d][:PER_LEAD]
        if got:
            photos[pid] = got
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(photos))
    return photos
