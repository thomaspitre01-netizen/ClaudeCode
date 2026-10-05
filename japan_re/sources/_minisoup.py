"""A stdlib stand-in for the small part of BeautifulSoup the parsers use.

Used only when bs4 is not installed (e.g. an environment that cannot reach PyPI).
Supports find / find_all by tag name(s) and attributes (True = present, a string,
or a compiled regex; `class_` too), recursive=False, get_text, tag['attr'], .get
and soup.title - nothing else.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
        'param', 'source', 'track', 'wbr'}
MULTI = {'class', 'rel', 'rev', 'headers', 'accesskey'}
NO_TEXT = {'script', 'style', 'template', 'noscript'}
# opening the key closes an open element in the set, but not past a boundary tag
IMPLICIT = {
    'dt': ({'dt', 'dd'}, {'dl'}), 'dd': ({'dt', 'dd'}, {'dl'}),
    'li': ({'li'}, {'ul', 'ol'}),
    'tr': ({'tr', 'td', 'th'}, {'table', 'tbody', 'thead', 'tfoot'}),
    'td': ({'td', 'th'}, {'tr', 'table'}), 'th': ({'td', 'th'}, {'tr', 'table'}),
    'tbody': ({'tbody', 'thead', 'tr', 'td', 'th'}, {'table'}),
    'thead': ({'tbody', 'thead', 'tr', 'td', 'th'}, {'table'}),
    'option': ({'option'}, {'select'}),
}


class Tag:
    def __init__(self, name: str, attrs: dict, parent: 'Tag | None' = None):
        self.name, self.attrs, self.parent = name, attrs, parent
        self.contents: list = []          # Tag or str

    # -- attribute access
    def get(self, key, default=None):
        return self.attrs.get(key, default)

    def __getitem__(self, key):
        return self.attrs[key]

    def __bool__(self):
        return True

    def __getattr__(self, name):          # soup.title, soup.h1 ...
        if name.startswith('_'):
            raise AttributeError(name)
        return self.find(name)

    # -- text
    def _strings(self):
        for c in self.contents:
            if isinstance(c, str):
                yield c
            elif c.name not in NO_TEXT:
                yield from c._strings()

    def get_text(self, separator: str = '', strip: bool = False) -> str:
        parts = self._strings()
        if strip:
            parts = (p.strip() for p in parts)
            parts = [p for p in parts if p]
        return separator.join(parts)

    @property
    def text(self) -> str:
        return self.get_text()

    # -- search
    def _descendants(self, recursive: bool):
        for c in self.contents:
            if isinstance(c, Tag):
                yield c
                if recursive:
                    yield from c._descendants(True)

    def find_all(self, name=None, attrs=None, recursive: bool = True, limit=None, **kw):
        want = dict(attrs or {})
        if 'class_' in kw:
            want['class'] = kw.pop('class_')
        want.update(kw)
        names = {name} if isinstance(name, str) else set(name) if name else None
        out = []
        for t in self._descendants(recursive):
            if names and t.name not in names:
                continue
            if all(_match(t.attrs.get(k), v) for k, v in want.items()):
                out.append(t)
                if limit and len(out) >= limit:
                    break
        return out

    def find(self, name=None, attrs=None, recursive: bool = True, **kw):
        r = self.find_all(name, attrs, recursive, limit=1, **kw)
        return r[0] if r else None

    def __repr__(self):
        return f'<{self.name} {self.attrs}>'


def _match(actual, want) -> bool:
    if want is True:
        return actual is not None
    if want is None or want is False:
        return actual is None
    if actual is None:
        return False
    values = actual if isinstance(actual, list) else [actual]
    candidates = values + ([' '.join(values)] if len(values) > 1 else [])
    if hasattr(want, 'search'):
        return any(want.search(v) for v in candidates)
    if isinstance(want, (list, tuple, set)):
        return any(v in want for v in candidates)
    return want in candidates


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Tag('[document]', {})
        self.stack = [self.root]

    def _close_to(self, i: int):
        del self.stack[i:]

    def handle_starttag(self, tag, attrs):
        if tag in IMPLICIT:
            closes, boundary = IMPLICIT[tag]
            for i in range(len(self.stack) - 1, 0, -1):
                n = self.stack[i].name
                if n in boundary:
                    break
                if n in closes:
                    self._close_to(i)
                    break
        elif tag == 'p' and self.stack[-1].name == 'p':
            self.stack.pop()
        d = {}
        for k, v in attrs:
            v = v if v is not None else ''
            d[k] = v.split() if k in MULTI else v
        parent = self.stack[-1]
        t = Tag(tag, d, parent)
        parent.contents.append(t)
        if tag not in VOID:
            self.stack.append(t)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack[-1].name == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].name == tag:
                self._close_to(i)
                return

    def handle_data(self, data):
        self.stack[-1].contents.append(data)


def BeautifulSoup(markup: str | bytes, features: str | None = None) -> Tag:  # noqa: N802
    if isinstance(markup, bytes):
        markup = markup.decode('utf-8', 'replace')
    b = _Builder()
    b.feed(markup)
    b.close()
    return b.root
