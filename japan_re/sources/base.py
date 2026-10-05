"""What every source shares: finding detail links, paging, and a generic page reader.

Japanese listing pages, whatever the site, put the facts in label/value pairs:
<dl><dt>価格</dt><dd>4,980万円</dd></dl> or <tr><th>土地面積</th><td>250m²</td></tr>.
`extract_pairs` collects all of them verbatim; `records.build` then maps the
labels it recognises onto columns. That keeps site-specific code down to "which
links are listings" and "where the search starts", which is the part that differs.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass, field

try:
    from bs4 import BeautifulSoup
except ImportError:          # no PyPI access: fall back to the stdlib reader
    from ._minisoup import BeautifulSoup

from ..normalize import nfkc


@dataclass
class ParsedListing:
    url: str
    source_id: str
    source_listing_id: str | None
    category_hint: str | None
    title: str | None = None
    pairs: dict[str, str] = field(default_factory=dict)       # label -> value, Japanese
    description: str | None = None
    images: list[str] = field(default_factory=list)
    lat: float | None = None
    lng: float | None = None


@dataclass
class SearchTarget:
    url: str
    category_hint: str      # detached_house | land | condominium | ...
    label: str              # 'Musashino / used houses', for logs


class Source:
    id: str = ''
    name: str = ''
    base_url: str = ''
    kind: str = 'agency'
    policy: str = 'unverified'
    policy_notes: str = ''
    enabled_by_default: bool = False
    detail_re: re.Pattern = re.compile(r'$^')
    max_pages_per_target: int = 30
    per_municipality: bool = True    # False: one index covers the whole site

    # -- to override --------------------------------------------------------
    def search_targets(self, munis, categories=('detached_house', 'land')) -> list[SearchTarget]:
        raise NotImplementedError

    def listing_id(self, url: str) -> str | None:
        m = self.detail_re.search(url)
        return m.group('id') if m and 'id' in m.groupdict() else None

    def canonical_url(self, url: str) -> str:
        p = urllib.parse.urlsplit(url)
        return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, p.query, ''))

    def extra_pages(self, url: str) -> list[str]:
        """More pages of the same listing worth reading (e.g. a full-spec tab)."""
        return []

    def category_from_url(self, url: str, default: str | None) -> str | None:
        return default

    # -- shared behaviour -----------------------------------------------------
    def detail_links(self, html: str, page_url: str) -> list[str]:
        soup = BeautifulSoup(html, 'html.parser')
        seen, out = set(), []
        host = urllib.parse.urlsplit(page_url).netloc
        for a in soup.find_all('a', href=True):
            href = urllib.parse.urljoin(page_url, a['href'])
            if urllib.parse.urlsplit(href).netloc != host:
                continue
            if self.detail_re.search(href):
                href = self.canonical_url(href)
                if href not in seen:
                    seen.add(href)
                    out.append(href)
        return out

    def next_page(self, html: str, page_url: str) -> str | None:
        soup = BeautifulSoup(html, 'html.parser')
        link = soup.find('link', rel='next') or soup.find('a', rel='next')
        if not link:
            for a in soup.find_all('a', href=True):
                if nfkc(a.get_text()) in ('次へ', '次へ>', '次のページ', '次の20件', '次の30件', '>', '次'):
                    link = a
                    break
        if link and link.get('href'):
            nxt = urllib.parse.urljoin(page_url, link['href'])
            return nxt if nxt != page_url else None
        return None

    def parse_detail(self, pages: list[tuple[str, str]], category_hint: str | None) -> ParsedListing:
        """pages: [(url, html), ...] - the main page first, then extra_pages()."""
        url = pages[0][0]
        out = ParsedListing(url=url, source_id=self.id, source_listing_id=self.listing_id(url),
                            category_hint=self.category_from_url(url, category_hint))
        for i, (purl, html) in enumerate(pages):
            soup = BeautifulSoup(html, 'html.parser')
            if i == 0:
                out.title = page_title(soup)
                out.images = images(soup, purl)
                out.lat, out.lng = coordinates(html)
            for k, v in extract_pairs(soup).items():
                out.pairs.setdefault(k, v)
            desc = description(soup, out.pairs)
            if desc and (not out.description or len(desc) > len(out.description)):
                out.description = desc
        return out


# ---------------------------------------------------------------- generic readers

def _text(el) -> str:
    return nfkc(el.get_text(' ', strip=True)) if el else ''


def page_title(soup: BeautifulSoup) -> str | None:
    og = soup.find('meta', property='og:title')
    if og and og.get('content'):
        return re.sub(r'\s*[|｜]\s*[^|｜]{1,20}$', '', nfkc(og['content'])) or None   # 'Title｜Site'
    h1 = soup.find('h1')
    if h1 and _text(h1):
        return _text(h1)
    return _text(soup.title) or None


_LABEL_OK = re.compile(r'^[^\d]{1,24}$')


def extract_pairs(soup: BeautifulSoup) -> dict[str, str]:
    """Every dt/dd and th/td pair on the page, labels cleaned of brackets and help
    icons ('価格 ヒント' -> '価格'). First occurrence of a label wins."""
    pairs: dict[str, str] = {}

    def add(label: str, value: str):
        label = re.sub(r'\s*(ヒント|\?|※.*|注\d*)$', '', nfkc(label)).strip(' :：')
        value = nfkc(value)
        if label and value and _LABEL_OK.match(label) and label not in pairs:
            pairs[label] = value[:2000]

    for dl in soup.find_all('dl'):
        dts, dds = dl.find_all('dt'), dl.find_all('dd')
        if dts and len(dts) == len(dds):
            for dt, dd in zip(dts, dds):
                add(_text(dt), _text(dd))
    for tr in soup.find_all('tr'):
        cells = tr.find_all(['th', 'td'], recursive=False)
        # th td th td ... rows (SUUMO's two-column spec tables)
        i = 0
        while i < len(cells) - 1:
            if cells[i + 1].name == 'td' and (cells[i].name == 'th' or _is_label_cell(cells[i])):
                add(_text(cells[i]), _text(cells[i + 1]))
                i += 2
            else:
                i += 1
    return pairs


_LABEL_CLASS = re.compile(r'(title|label|head|name|item)', re.I)
_VALUE_CLASS = re.compile(r'(content|value|data|body|detail)', re.I)


def _is_label_cell(td) -> bool:
    """<td class="td_gaiyou_title1">建物構造</td><td class="td_gaiyou_content1">...: the R不動産
    spec table marks its label cells by class instead of using <th>."""
    cls = ' '.join(td.get('class') or [])
    return bool(_LABEL_CLASS.search(cls)) and not _VALUE_CLASS.search(cls)


_DESC_CLASS = re.compile(r'(comment|appeal|point|description|feature|remarks|detail[-_]?text|'
                         r'catch|pr[-_]|message|introduction|body|article|entry)', re.I)
_DESC_LABELS = ('セールスポイント', 'おすすめポイント', '物件の特徴', '備考', '特記事項', 'その他',
                'コメント', '担当者コメント', 'PR', '物件説明', '周辺環境')


def description(soup: BeautifulSoup, pairs: dict[str, str]) -> str | None:
    """The free-text description: the longest block of prose on the page, plus any
    remarks fields. Kept in Japanese; translation happens later."""
    chunks = [f'{k}: {pairs[k]}' for k in _DESC_LABELS if k in pairs]
    best = ''
    for el in soup.find_all(['div', 'section', 'p', 'article'], class_=_DESC_CLASS):
        t = _text(el)
        if len(t) > len(best) and len(t) < 8000:
            best = t
    if not best:
        for p in soup.find_all('p'):
            t = _text(p)
            if len(t) > len(best) and len(t) >= 40:   # unlabelled prose must be substantial
                best = t
    if best:
        chunks.insert(0, best)
    meta = soup.find('meta', attrs={'name': 'description'})
    if not chunks and meta and meta.get('content'):
        chunks.append(nfkc(meta['content']))
    return '\n\n'.join(chunks) or None


_IMG_SKIP = re.compile(r'(logo|icon|banner|btn|button|sprite|spacer|blank|loading|arrow|common)', re.I)


def images(soup: BeautifulSoup, page_url: str, limit: int = 20) -> list[str]:
    out = []
    og = soup.find('meta', property='og:image')
    if og and og.get('content'):
        out.append(urllib.parse.urljoin(page_url, og['content']))
    for img in soup.find_all('img'):
        src = img.get('data-src') or img.get('data-original') or img.get('src') or ''
        if not re.search(r'\.(jpe?g|webp|png)(\?|$)', src, re.I) or _IMG_SKIP.search(src):
            continue
        u = urllib.parse.urljoin(page_url, src)
        if u not in out:
            out.append(u)
        if len(out) >= limit:
            break
    return out


_LAT = re.compile(r'''["']?(?:lat|latitude|ido)["']?\s*[:=]\s*["']?(3[0-9]\.\d{3,})''', re.I)
_LNG = re.compile(r'''["']?(?:lng|lon|long|longitude|keido)["']?\s*[:=]\s*["']?(1[34][0-9]\.\d{3,})''', re.I)
_PAIR = re.compile(r'(?:[?&](?:q|ll|center)=|@)(3[0-9]\.\d{3,}),\s*(1[34][0-9]\.\d{3,})')


def coordinates(html: str) -> tuple[float | None, float | None]:
    """Coordinates the page itself publishes (map widgets, JSON-LD, Google Maps links).
    Only accepted inside a box around the Kanto plain."""
    for m in _PAIR.finditer(html):
        lat, lng = float(m.group(1)), float(m.group(2))
        if 34.8 < lat < 36.5 and 138.5 < lng < 140.5:
            return lat, lng
    lat, lng = _LAT.search(html), _LNG.search(html)
    if lat and lng:
        la, ln = float(lat.group(1)), float(lng.group(1))
        if 34.8 < la < 36.5 and 138.5 < ln < 140.5:
            return la, ln
    for block in re.findall(r'<script[^>]+ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        geo = data.get('geo') if isinstance(data, dict) else None
        if isinstance(geo, dict) and geo.get('latitude'):
            return float(geo['latitude']), float(geo['longitude'])
    return None, None
