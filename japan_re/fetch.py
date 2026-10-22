"""A polite HTTP client. Every page fetch in this project goes through it.

House rules, all on by default and none of them switchable off from the CLI:
  * robots.txt is read first and obeyed, including '*' and '$' wildcards (Python's
    urllib.robotparser ignores them, which would silently allow paths like
    '/*/ajax/' that a site has asked robots to skip)
  * one request at a time per host, at least MIN_DELAY seconds apart, or the site's
    Crawl-delay if that is longer
  * an honest User-Agent naming the tool and an operator contact
  * a 403 or a CAPTCHA page stops that host for the rest of the run. The client
    never rotates agents, proxies or headers to get round a block.
  * every fetched page is kept (gzipped) under data/raw/, so parsers can be re-run
    without refetching
"""
from __future__ import annotations

import gzip
import hashlib
import os
import random
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

import requests

UA_TOKEN = 'japan-re-research'
UA = (f'{UA_TOKEN}/0.1 (private property research; low-rate; '
      'contact: {contact})')
MIN_DELAY = 6.0          # seconds between requests to one host
MAX_RETRIES = 3


class Blocked(Exception):
    """The host refused us (403/CAPTCHA). Stop crawling it; do not work around it."""


class Disallowed(Exception):
    """robots.txt disallows this URL for our agent."""


@dataclass
class RobotsRules:
    """Google-style robots.txt matching: longest matching rule wins, Allow wins ties."""
    rules: list[tuple[bool, str]] = field(default_factory=list)   # (allow, pattern)
    crawl_delay: float | None = None
    fetched: bool = True

    @staticmethod
    def parse(text: str, agent: str = UA_TOKEN) -> 'RobotsRules':
        groups: list[tuple[list[str], list[tuple[bool, str]], float | None]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        delay = None
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split('#', 1)[0].strip()
            if ':' not in line:
                continue
            key, val = (x.strip() for x in line.split(':', 1))
            key = key.lower()
            if key == 'user-agent':
                if not last_was_agent and agents:
                    groups.append((agents, rules, delay))
                    agents, rules, delay = [], [], None
                agents.append(val.lower())
                last_was_agent = True
                continue
            last_was_agent = False
            if key in ('allow', 'disallow') and agents:
                if val == '' and key == 'disallow':
                    continue  # empty Disallow = allow everything
                rules.append((key == 'allow', val))
            elif key == 'crawl-delay' and agents:
                try:
                    delay = float(val)
                except ValueError:
                    pass
        if agents:
            groups.append((agents, rules, delay))
        agent = agent.lower()
        mine = [g for g in groups if any(a != '*' and a in agent for a in g[0])]
        chosen = mine or [g for g in groups if '*' in g[0]]
        out = RobotsRules()
        for _, r, d in chosen:
            out.rules.extend(r)
            if d is not None:
                out.crawl_delay = max(out.crawl_delay or 0, d)
        return out

    @staticmethod
    def _to_regex(pattern: str) -> re.Pattern:
        anchored = pattern.endswith('$')
        body = pattern[:-1] if anchored else pattern
        rx = '.*'.join(re.escape(part) for part in body.split('*'))
        return re.compile('^' + rx + ('$' if anchored else ''))

    def allowed(self, url: str) -> bool:
        p = urllib.parse.urlsplit(url)
        path = (p.path or '/') + (('?' + p.query) if p.query else '')
        best: tuple[int, bool] | None = None
        for allow, pattern in self.rules:
            if self._to_regex(pattern).match(path):
                key = (len(pattern), allow)
                if best is None or key > best:
                    best = key
        return True if best is None else best[1]


_CAPTCHA = re.compile(r'captcha|アクセスが集中|不正なアクセス|access denied|robot check', re.I)


class PoliteClient:
    def __init__(self, contact: str | None = None, raw_dir: str | Path = 'data/raw',
                 min_delay: float = MIN_DELAY, timeout: float = 30.0):
        contact = contact or os.environ.get('JRE_CONTACT', 'unset')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': UA.format(contact=contact),
            'Accept-Language': 'ja,en;q=0.5',
        })
        self.raw_dir = Path(raw_dir)
        self.min_delay = min_delay
        self.timeout = timeout
        self._robots: dict[str, RobotsRules] = {}
        self._last: dict[str, float] = {}
        self._blocked: set[str] = set()
        self.stats = {'requests': 0, 'robots_blocked': 0, 'errors': 0}

    # -- robots -----------------------------------------------------------
    def robots(self, url: str) -> RobotsRules:
        host = urllib.parse.urlsplit(url).netloc
        if host not in self._robots:
            scheme = urllib.parse.urlsplit(url).scheme or 'https'
            try:
                self._wait(host, 1.0)
                r = self.session.get(f'{scheme}://{host}/robots.txt', timeout=self.timeout)
                self.stats['requests'] += 1
                if r.status_code in (401, 403):
                    # Treat a refused robots.txt as "disallow all", per RFC 9309.
                    rules = RobotsRules(rules=[(False, '/')])
                elif r.status_code >= 400:
                    rules = RobotsRules()           # no robots.txt: everything allowed
                else:
                    rules = RobotsRules.parse(r.text)
            except requests.RequestException:
                # Unreachable robots.txt: be conservative, fetch nothing this run.
                rules = RobotsRules(rules=[(False, '/')], fetched=False)
            self._robots[host] = rules
        return self._robots[host]

    def allowed(self, url: str) -> bool:
        return self.robots(url).allowed(url)

    # -- fetching ---------------------------------------------------------
    def _wait(self, host: str, delay: float):
        last = self._last.get(host)
        if last is not None:
            gap = delay + random.uniform(0, delay * 0.3) - (time.monotonic() - last)
            if gap > 0:
                time.sleep(gap)
        self._last[host] = time.monotonic()

    def get(self, url: str) -> 'Page':
        host = urllib.parse.urlsplit(url).netloc
        if host in self._blocked:
            raise Blocked(host)
        rules = self.robots(url)
        if not rules.fetched:
            self.stats['robots_blocked'] += 1
            raise Disallowed(f'robots.txt for {host} could not be read (network blocked?); '
                             f'nothing fetched from it: {url}')
        if not rules.allowed(url):
            self.stats['robots_blocked'] += 1
            raise Disallowed(f'robots.txt disallows {url}')
        delay = max(self.min_delay, rules.crawl_delay or 0)
        for attempt in range(MAX_RETRIES):
            self._wait(host, delay * (2 ** attempt))
            try:
                r = self.session.get(url, timeout=self.timeout)
            except requests.RequestException:
                self.stats['errors'] += 1
                continue
            self.stats['requests'] += 1
            if r.status_code == 403 or (r.status_code == 200 and len(r.text) < 5000
                                        and _CAPTCHA.search(r.text)):
                self._blocked.add(host)
                raise Blocked(f'{host} answered {r.status_code}; stopping this host')
            if r.status_code == 429 or r.status_code >= 500:
                continue
            if not r.encoding or r.encoding.lower() == 'iso-8859-1':
                r.encoding = r.apparent_encoding   # many JP sites send Shift_JIS/EUC-JP
            return Page(url=r.url, status=r.status_code, html=r.text,
                        raw_path=self._store(url, r.content) if r.status_code == 200 else None)
        self.stats['errors'] += 1
        return Page(url=url, status=0, html='', raw_path=None)

    def _store(self, url: str, content: bytes) -> str:
        host = urllib.parse.urlsplit(url).netloc
        digest = hashlib.sha1(url.encode()).hexdigest()[:16]
        stamp = time.strftime('%Y%m%d')
        path = self.raw_dir / host / f'{digest}-{stamp}.html.gz'
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, 'wb') as f:
            f.write(content)
        return str(path)


@dataclass
class Page:
    url: str
    status: int
    html: str
    raw_path: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200 and bool(self.html)
