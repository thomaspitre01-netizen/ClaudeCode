"""A deliberately polite crawler for IFA firm websites.

What to expect: Singapore IFA firms publish desk addresses (enquiry@, ask@) and the
occasional named adviser or branch manager. They do not publish their whole adviser
roster, so this returns tens of addresses, not thousands. The pattern engine is what
fills the roster; this is what confirms a domain is real and finds branch contacts.

House rules, all on by default:
  * robots.txt is fetched first and obeyed - a Disallow means the page is not fetched
  * one request at a time per domain, with a delay (crawl-delay honoured if declared)
  * a page budget per domain, so a bad link graph cannot turn into a hammering
  * an honest User-Agent naming the operator, so a webmaster can identify the traffic
  * same-site only: no wandering off onto third-party domains
"""
from __future__ import annotations

import html
import re
import time
import urllib.parse
import urllib.robotparser
from collections import deque
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

from .patterns import is_placeholder, is_role_account

DEFAULT_UA = ('IFA-Contact-Research/1.0 (business contact research; '
              'contact: {operator_email})')

# Pages worth walking towards; anything else is a lower priority.
INTERESTING = re.compile(
    r'(team|about|adviser|advisor|consultant|people|staff|leader|management|'
    r'contact|branch|office|our-|meet|profile|directory|partner)', re.I)

SKIP_EXT = re.compile(r'\.(pdf|jpe?g|png|gif|svg|webp|zip|docx?|xlsx?|pptx?|mp4|mp3|ico|css|js)$', re.I)

# Extraction has to be strict, because prose is full of things that look like
# addresses once you squint. An earlier, looser version read the sentence
# "...estate. Investment..." as est@e.investment, because it treated the letters
# "at" inside a word as an @ sign. Two rules keep that out:
#   1. the top-level domain must be one that exists
#   2. the domain match is non-greedy, so "pdpa@ippfa.com. If you" yields
#      pdpa@ippfa.com and not pdpa@ippfa.com.if
_MULTI_SUFFIX = ['com.sg', 'com.my', 'com.hk', 'com.au', 'com.cn', 'com.tw', 'com.ph',
                 'com.vn', 'co.uk', 'co.id', 'co.in', 'co.th', 'co.jp', 'co.nz',
                 'net.sg', 'org.sg', 'edu.sg', 'gov.sg', 'net.au', 'org.au']
_TLD = ['com', 'net', 'org', 'edu', 'gov', 'int', 'biz', 'info', 'asia', 'name', 'pro',
        'io', 'ai', 'co', 'me', 'app', 'dev', 'xyz', 'online', 'site', 'tech', 'cloud',
        'group', 'capital', 'finance', 'fund', 'global', 'partners', 'wealth', 'agency',
        'advisory', 'financial', 'insurance', 'life', 'world', 'company', 'consulting',
        'sg', 'my', 'hk', 'cn', 'tw', 'jp', 'kr', 'id', 'ph', 'th', 'vn', 'in', 'au',
        'nz', 'uk', 'ie', 'us', 'ca', 'de', 'fr', 'nl', 'es', 'it', 'ch', 'se', 'dk',
        'no', 'fi', 'be', 'pt', 'pl', 'cz', 'ru', 'za', 'ae', 'sa', 'il', 'tr', 'br',
        'mx', 'ar', 'cl']
_SUFFIX_ALT = '|'.join(re.escape(s) for s in _MULTI_SUFFIX + _TLD)

EMAIL_RE = re.compile(
    r'(?<![A-Za-z0-9._%+\-])'
    r'([A-Za-z0-9._%+\-]{2,64})@'
    r'((?:[A-Za-z0-9\-]+\.)+?(?:' + _SUFFIX_ALT + r'))'
    r'(?![A-Za-z0-9\-])', re.I)

# Only bracketed obfuscation is accepted - "name (at) firm (dot) com". A bare "at"
# between words is prose far more often than it is an address.
OBFUSCATED_RE = re.compile(
    r'(?<![A-Za-z0-9])([A-Za-z0-9._%+\-]{2,64})\s*[\[\(\{]\s*(?:at|@)\s*[\]\)\}]\s*'
    r'([A-Za-z0-9.\-]+?)\s*(?:[\[\(\{]\s*dot\s*[\]\)\}]|\.)\s*'
    r'(' + '|'.join(re.escape(t) for t in _TLD) + r')(?![A-Za-z0-9])', re.I)

# A local part that is a bare English word is nearly always a false positive from
# running text; a real one carries a name, an initial or a separator.
_PROSE_LOCALS = {
    'with', 'from', 'about', 'this', 'that', 'these', 'those', 'your', 'our', 'their',
    'and', 'the', 'for', 'you', 'we', 'it', 'is', 'are', 'was', 'were', 'been', 'have',
    'has', 'will', 'can', 'may', 'more', 'most', 'other', 'others', 'please', 'here',
    'read', 'see', 'learn', 'find', 'get', 'available', 'both', 'she', 'he', 'they',
}

NAME_RE = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b')


def decode_cfemail(hexstr: str) -> str | None:
    """Cloudflare obscures published addresses with a trivial XOR; this reads the
    same text a browser would render. It is not a protection bypass."""
    try:
        data = bytes.fromhex(hexstr)
        key = data[0]
        return ''.join(chr(b ^ key) for b in data[1:])
    except (ValueError, IndexError):
        return None


@dataclass
class Hit:
    email: str
    domain: str
    source_url: str
    nearby_name: str = ''
    is_role: bool = False


@dataclass
class CrawlReport:
    seed: str
    pages_fetched: int = 0
    pages_blocked_by_robots: int = 0
    hits: list[Hit] = field(default_factory=list)
    error: str = ''


def _registrable(host: str) -> str:
    """Good-enough eTLD+1 for the .com.sg / .sg / .com shapes in scope."""
    parts = host.lower().lstrip('.').split('.')
    if len(parts) >= 3 and parts[-2] in {'com', 'net', 'org', 'edu', 'gov'} and len(parts[-1]) == 2:
        return '.'.join(parts[-3:])
    return '.'.join(parts[-2:]) if len(parts) >= 2 else host


def _extract(soup: BeautifulSoup, raw: str, url: str) -> list[Hit]:
    found: dict[str, Hit] = {}

    def add(addr: str, name: str = '', from_markup: bool = False):
        addr = addr.strip().strip('.,;:').lower()
        if not addr or '@' not in addr or SKIP_EXT.search(addr):
            return
        local, _, dom = addr.partition('@')
        if '.' not in dom or len(local) > 64 or len(dom) > 253:
            return
        # image filenames and tracking pixels sometimes look like addresses
        if re.search(r'\.(png|jpe?g|gif|webp|svg)$', dom):
            return
        # anything scraped out of running text has to clear the prose filter;
        # a mailto: link is explicit and is trusted as-is
        if not from_markup and local in _PROSE_LOCALS:
            return
        if is_placeholder(addr):
            return
        hit = found.get(addr)
        if hit is None:
            found[addr] = Hit(addr, dom, url, name, is_role_account(local))
        elif name and not hit.nearby_name:
            hit.nearby_name = name

    for a in soup.select('a[href^=mailto i]'):
        addr = urllib.parse.unquote(a['href'][7:].split('?')[0])
        # the anchor's own container often holds the person's name
        block = a.find_parent(['li', 'td', 'div', 'article', 'section', 'p'])
        m = NAME_RE.search(block.get_text(' ', strip=True)) if block else None
        add(addr, m.group(1) if m else '', from_markup=True)

    for el in soup.select('[data-cfemail]'):
        dec = decode_cfemail(el['data-cfemail'])
        if dec:
            add(dec, from_markup=True)

    text = soup.get_text(' ', strip=True)
    for m in EMAIL_RE.finditer(html.unescape(text)):
        add(f'{m.group(1)}@{m.group(2)}')
    for m in OBFUSCATED_RE.finditer(text):
        add(f'{m.group(1)}@{m.group(2)}.{m.group(3)}')
    # addresses that only appear in markup (JSON-LD, data attributes)
    for m in EMAIL_RE.finditer(html.unescape(raw)):
        add(f'{m.group(1)}@{m.group(2)}')

    return list(found.values())


def crawl_site(seed: str, operator_email: str, max_pages: int = 40,
               delay: float = 2.0, timeout: int = 20,
               obey_robots: bool = True, verbose: bool = False) -> CrawlReport:
    """Walk one site within its own rules and return the addresses it publishes."""
    rep = CrawlReport(seed=seed)
    parsed = urllib.parse.urlparse(seed if '://' in seed else 'https://' + seed)
    root = f'{parsed.scheme}://{parsed.netloc}'
    site = _registrable(parsed.netloc)
    ua = DEFAULT_UA.format(operator_email=operator_email)

    rp = urllib.robotparser.RobotFileParser()
    session = requests.Session()
    session.headers['User-Agent'] = ua

    if obey_robots:
        try:
            r = session.get(f'{root}/robots.txt', timeout=timeout)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except requests.RequestException:
            rp.parse([])                      # unreachable robots.txt = no stated rules
        declared = rp.crawl_delay(ua) or rp.crawl_delay('*')
        if declared:
            delay = max(delay, float(declared))

    seen: set[str] = set()
    queue: deque[str] = deque([seed if '://' in seed else 'https://' + seed])

    while queue and rep.pages_fetched < max_pages:
        url = queue.popleft()
        url, _ = urllib.parse.urldefrag(url)
        if url in seen:
            continue
        seen.add(url)

        if obey_robots and not rp.can_fetch(ua, url):
            rep.pages_blocked_by_robots += 1
            continue

        try:
            resp = session.get(url, timeout=timeout, allow_redirects=True)
        except requests.RequestException as exc:
            if url == queue and not rep.pages_fetched:
                rep.error = str(exc)[:200]
            continue
        finally:
            time.sleep(delay)

        if resp.status_code != 200 or 'html' not in resp.headers.get('content-type', ''):
            if rep.pages_fetched == 0 and not rep.error:
                rep.error = f'HTTP {resp.status_code}'
            continue

        rep.pages_fetched += 1
        soup = BeautifulSoup(resp.text, 'lxml')
        rep.hits.extend(_extract(soup, resp.text, url))
        if verbose:
            print(f'    [{rep.pages_fetched:>2}] {url}  (+{len(rep.hits)} total)')

        priority, normal = [], []
        for a in soup.find_all('a', href=True):
            nxt = urllib.parse.urljoin(url, a['href'])
            p = urllib.parse.urlparse(nxt)
            if p.scheme not in ('http', 'https') or _registrable(p.netloc) != site:
                continue
            if SKIP_EXT.search(p.path) or nxt in seen:
                continue
            (priority if INTERESTING.search(p.path) else normal).append(nxt)
        queue.extend(priority)
        queue.extend(normal[:10])

    # collapse duplicates found on several pages
    uniq: dict[str, Hit] = {}
    for h in rep.hits:
        if h.email not in uniq or (h.nearby_name and not uniq[h.email].nearby_name):
            uniq[h.email] = h
    rep.hits = sorted(uniq.values(), key=lambda h: (h.is_role, h.email))
    return rep
