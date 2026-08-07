"""Learn each firm's email format from the addresses you already hold, then predict
the missing ones.

The workbook carries 253 known addresses across 23 domains. Every firm uses one house
format (proinvest.com.sg is first.last, synergy.com.sg is firstlast, and so on), so a
name without an address can be filled in with a confidence score attached rather than
guessed by hand.

Accuracy is measured leave-one-out: each known address is predicted from a pattern
learned on the *other* addresses at that domain, so the score is not fitted to itself.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

# Titles and honorifics that are not part of anybody's email address.
_STRIP_TOKENS = {'mr', 'mrs', 'ms', 'miss', 'dr', 'prof', 'sir', 'madam', 'mdm'}

# A bracketed or quoted nickname - "Tan Wei Ming (Jerry)" - is dropped before splitting.
_PARENS = re.compile(r'[\(\["“].*?[\)\]"”]')


def name_tokens(name: str) -> list[str]:
    """Reduce a display name to lowercase ASCII word tokens."""
    n = _PARENS.sub(' ', name or '')
    n = unicodedata.normalize('NFKD', n).encode('ascii', 'ignore').decode()
    n = n.replace('@', ' ').replace('/', ' ')
    toks = [t for t in re.split(r"[^A-Za-z]+", n) if t]
    toks = [t.lower() for t in toks if t.lower() not in _STRIP_TOKENS]
    return toks


# ---------------------------------------------------------------------------
# Finding the surname.
#
# A Singapore Chinese name most often reads [Western given name] [surname]
# [Chinese given names] - "Daniel Ong Thiam Chye" is Mr Ong, not Mr Chye - but it
# also appears as [surname] [given names] ("Tan Yong Guan") and in plain Western
# order ("Johnny Nimrod Chan"). Taking the last token as the surname, which is the
# usual default, gets the commonest Singaporean shape wrong every time, so the
# surname is located by dictionary instead of by position.
# ---------------------------------------------------------------------------

# Romanised surnames common in Singapore (Hokkien/Teochew/Cantonese/Hakka variants),
# plus the Malay and Indian family names that appear in adviser rosters.
SURNAMES = {
    'tan', 'lim', 'lee', 'ng', 'ong', 'wong', 'goh', 'chua', 'chan', 'koh', 'teo',
    'ang', 'yeo', 'tay', 'ho', 'low', 'toh', 'sim', 'chia', 'seah', 'neo', 'chew',
    'loh', 'foo', 'heng', 'kwek', 'quek', 'soh', 'tham', 'yap', 'poh', 'chong',
    'cheng', 'chin', 'chow', 'chu', 'fong', 'han', 'hong', 'hu', 'huang', 'kang',
    'khoo', 'ko', 'kok', 'kong', 'lau', 'leong', 'leow', 'li', 'liew', 'lin', 'ling',
    'liu', 'loo', 'lu', 'mak', 'mok', 'oh', 'pang', 'peh', 'phua', 'pua', 'see',
    'seet', 'seow', 'shen', 'sng', 'song', 'su', 'sun', 'tang', 'tee', 'teng',
    'thio', 'tong', 'wang', 'wee', 'woo', 'wu', 'xu', 'yan', 'yang', 'yee', 'yong',
    'yu', 'yuen', 'zhang', 'zhu', 'zhou', 'cheah', 'cheok', 'chng', 'choo', 'gan',
    'hoe', 'kee', 'kho', 'lai', 'lam', 'loke', 'luo', 'ma', 'mah', 'oon', 'ow',
    'pan', 'pek', 'png', 'sia', 'siow', 'tai', 'tam', 'teoh', 'thng', 'tng', 'wan',
    'yao', 'yin', 'yip', 'yow', 'zeng', 'chee', 'cheo', 'chok', 'chuah', 'hoo',
    'kuah', 'kuek', 'lek', 'liang', 'lok', 'nai', 'ngo', 'sin', 'tak', 'tio', 'yeoh',
    'boon', 'keok', 'gay', 'hwang', 'ni', 'wei', 'ying', 'yoong', 'jiang', 'guo',
    'chun', 'kng', 'chee', 'loy', 'goh', 'lye', 'sia', 'kwok', 'tham', 'chiam',
    # Malay / Indian
    'bin', 'binte', 'binti', 'abdullah', 'ahmad', 'hassan', 'ibrahim', 'ismail',
    'osman', 'rahman', 'said', 'sukor', 'kumar', 'singh', 'nair', 'menon', 'pillai',
    'raj', 'rao', 'sharma', 'reddy', 'patel', 'shah',
}


def split_name(toks: list[str]) -> tuple[list[str], str] | None:
    """Return (given-name tokens, surname). None when the name is a single token.

    The first token that is a known surname wins, except that a lone leading surname
    with nothing after it cannot be right. When no token is recognised, the Western
    default applies and the last token is taken as the surname.
    """
    if len(toks) < 2:
        return None
    for i, t in enumerate(toks):
        if t in SURNAMES and (i > 0 or len(toks) > 1):
            given = toks[:i] + toks[i + 1:]
            if given:
                return given, t
    return toks[:-1], toks[-1]


def _s(fmt):
    """Pattern expressed over (given tokens, surname) rather than position."""
    def build(toks: list[str]) -> str | None:
        parsed = split_name(toks)
        if not parsed:
            return None
        given, sur = parsed
        g = ''.join(given)
        return fmt.format(given=g, sur=sur, g=g[0], s=sur[0],
                          given_dot='.'.join(given), first=given[0], f=given[0][0])
    return build


# ---------------------------------------------------------------------------
# Pattern vocabulary. Each pattern maps tokens to a local part, returning None when
# the name has too few tokens to satisfy it.
# ---------------------------------------------------------------------------

def _p(fmt, first_idx=0, last_idx=-1):
    def build(toks: list[str]) -> str | None:
        if len(toks) < 2:
            return None
        a, b = toks[first_idx], toks[last_idx]
        if a == b:
            return None
        return fmt.format(first=a, last=b, f=a[0], l=b[0])
    return build


PATTERNS: dict[str, callable] = {
    'first.last':   _p('{first}.{last}'),
    'firstlast':    _p('{first}{last}'),
    'first_last':   _p('{first}_{last}'),
    'first-last':   _p('{first}-{last}'),
    'f.last':       _p('{f}.{last}'),
    'flast':        _p('{f}{last}'),
    'first.l':      _p('{first}.{l}'),
    'firstl':       _p('{first}{l}'),
    'fl':           _p('{f}{l}'),
    'last.first':   _p('{last}.{first}'),
    'lastfirst':    _p('{last}{first}'),
    'lastf':        _p('{last}{f}'),
    # three-token names where the middle token, not the final one, is the surname
    'first.mid':    _p('{first}.{last}', last_idx=1),
    'firstmid':     _p('{first}{last}', last_idx=1),
    # surname-aware forms: the surname is found by dictionary, wherever it sits
    'given.sur':    _s('{first}.{sur}'),      # Daniel Ong Thiam Chye -> daniel.ong
    'givensur':     _s('{first}{sur}'),       # Daniel Ong Thiam Chye -> danielong
    'allgiven.sur': _s('{given}.{sur}'),      # Giau Kim Low          -> giaukim.low
    'allgivensur':  _s('{given}{sur}'),
    'sur.allgiven': _s('{sur}.{given}'),      # Tan Yong Guan         -> tan.yongguan
    'surallgiven':  _s('{sur}{given}'),
    'f.sur':        _s('{f}.{sur}'),
    'fsur':         _s('{f}{sur}'),
    # single-token forms
    'first':        lambda t: t[0] if t else None,
    'last':         lambda t: t[-1] if t else None,
    'alltokens':    lambda t: ''.join(t) if len(t) >= 2 else None,
    'alltokens.':   lambda t: '.'.join(t) if len(t) >= 2 else None,
    'initials+last': lambda t: (''.join(x[0] for x in t[:-1]) + t[-1]) if len(t) >= 2 else None,
}

# Addresses that belong to a desk rather than a person. They are real and often useful
# for branch-level outreach, but they must never be used to learn a personal pattern.
ROLE_LOCALPARTS = {
    'info', 'enquiry', 'enquiries', 'admin', 'contact', 'sales', 'support', 'hello',
    'ask', 'help', 'general', 'office', 'mail', 'marketing', 'hr', 'careers', 'jobs',
    'compliance', 'legal', 'finance', 'accounts', 'billing', 'service', 'customercare',
    'advice', 'team', 'partners', 'no-reply', 'noreply', 'donotreply', 'webmaster',
    'postmaster', 'abuse', 'privacy', 'dpo', 'feedback', 'invest', 'client', 'clients',
    # compliance and data-protection desks, common on Singapore FA sites
    'pdpa', 'mypersonaldata', 'personaldata', 'marketconduct', 'chru', 'complaints',
    'whistleblowing', 'audit', 'risk', 'operations', 'ops', 'reception', 'training',
}

# Addresses that only exist as form placeholders or documentation examples.
PLACEHOLDER_DOMAINS = {'domain.com', 'example.com', 'example.org', 'email.com',
                       'yourdomain.com', 'company.com', 'gmail.co', 'abc.com'}
PLACEHOLDER_LOCALS = {'user', 'username', 'yourname', 'your-name', 'name', 'email',
                      'youremail', 'firstname', 'lastname', 'someone', 'test'}


def is_placeholder(email: str) -> bool:
    local, _, domain = email.lower().partition('@')
    return domain in PLACEHOLDER_DOMAINS or local in PLACEHOLDER_LOCALS

FREE_MAIL = {
    'gmail.com', 'yahoo.com', 'yahoo.com.sg', 'hotmail.com', 'outlook.com', 'live.com',
    'icloud.com', 'me.com', 'qq.com', '163.com', 'proton.me', 'protonmail.com',
}


def is_role_account(local: str) -> bool:
    base = re.split(r'[.\-_+]', local.lower())[0]
    return local.lower() in ROLE_LOCALPARTS or base in ROLE_LOCALPARTS


# Some houses append the initials of the given names we do not hold:
# Phillip Capital turns "Isabelle Tee Ying Zi" into isabelleteeyz. The style is
# recognisable but not reproducible from a truncated name, so it has to be reported
# rather than predicted.
_SUFFIX_INITIALS = re.compile(r'^[a-z]{1,4}$')


def _suffix_style_hits(pairs: list[tuple[str, str]]) -> float:
    """Share of addresses that are 'our tokens, then a short unexplained suffix'."""
    hits = attempts = 0
    for name, local in pairs:
        toks = name_tokens(name)
        if len(toks) < 2:
            continue
        attempts += 1
        stem = ''.join(toks)
        if local.startswith(stem) and _SUFFIX_INITIALS.match(local[len(stem):] or 'x'):
            hits += 1
        elif len(toks) >= 3:
            # first + surname + initials of the middle tokens
            stem2 = toks[0] + toks[-1]
            if local.startswith(stem2) and _SUFFIX_INITIALS.match(local[len(stem2):] or 'x'):
                hits += 1
    return hits / attempts if attempts else 0.0


@dataclass
class DomainModel:
    """The house email format for one domain."""
    domain: str
    pattern: str | None = None
    confidence: float = 0.0          # share of known addresses the pattern reproduces
    samples: int = 0                 # personal addresses used to learn it
    runners_up: list[tuple[str, float]] = field(default_factory=list)
    predictable: bool = True
    style_note: str = ''

    def row_confidence(self, name: str) -> float:
        """Domain confidence adjusted for how hard this particular name is.

        Measured on this dataset, a learned pattern reproduces 83% of two-token names
        but only 27% of three-token ones, because firms disagree about which parts of
        a Singaporean name reach the address ("Paul See Hock Soon" became paul.see,
        "Stella Sophia Goh" became stellasophia.goh). The penalty is that ratio, so a
        long name has to clear the bar on the strength of its domain alone.
        """
        return self.confidence * (1.0 if len(name_tokens(name)) <= 2 else 0.33)

    def verdict(self, min_confidence: float) -> str:
        if not self.predictable:
            return 'needs-full-name'
        if self.pattern is None or self.samples < 2:
            return 'insufficient-evidence'
        if self.confidence >= min_confidence:
            return 'predict'
        return 'ambiguous'

    def predict(self, name: str) -> str | None:
        if not self.pattern:
            return None
        local = PATTERNS[self.pattern](name_tokens(name))
        return f'{local}@{self.domain}' if local else None

    def alternatives(self, name: str, k: int = 3) -> list[str]:
        toks = name_tokens(name)
        primary = self.predict(name)
        # for a 3+ token name the rival reading is worth showing even if it did not
        # win the domain, because firms are inconsistent about exactly these names
        rivals = ['given.sur', 'allgiven.sur', 'givensur', 'allgivensur'] if len(toks) >= 3 else []
        out = []
        for pat in [p for p, _ in self.runners_up] + rivals:
            local = PATTERNS[pat](toks)
            if not local:
                continue
            cand = f'{local}@{self.domain}'
            if cand != primary and cand not in out:
                out.append(cand)
            if len(out) >= k:
                break
        return out


def _score_patterns(pairs: list[tuple[str, str]]) -> list[tuple[str, float]]:
    """pairs = [(display name, local part)]. Returns patterns ranked by hit rate."""
    scored = []
    for pat, build in PATTERNS.items():
        hits = attempts = 0
        for name, local in pairs:
            got = build(name_tokens(name))
            if got is None:
                continue
            attempts += 1
            hits += (got == local)
        # a pattern that only applies to a couple of names is not evidence of a house style
        if attempts >= max(1, len(pairs) // 2):
            scored.append((pat, hits / attempts))
    surname_aware = {'given.sur', 'givensur', 'allgiven.sur', 'allgivensur',
                     'sur.allgiven', 'surallgiven', 'f.sur', 'fsur'}
    scored.sort(key=lambda kv: (-kv[1], kv[0] not in surname_aware, kv[0]))
    return scored


def learn(contacts: list[dict]) -> dict[str, DomainModel]:
    """Build one DomainModel per email domain seen in the contact list."""
    by_domain: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for c in contacts:
        email = (c.get('email') or '').strip().lower()
        if '@' not in email:
            continue
        local, _, domain = email.partition('@')
        if domain in FREE_MAIL or is_role_account(local):
            continue
        by_domain[domain].append((c.get('name', ''), local))

    models = {}
    for domain, pairs in by_domain.items():
        scored = _score_patterns(pairs)
        best = scored[0] if scored else (None, 0.0)
        model = DomainModel(
            domain=domain,
            pattern=best[0] if best[1] > 0 else None,
            confidence=best[1],
            samples=len(pairs),
            runners_up=[s for s in scored[1:] if s[1] > 0][:4],
        )
        # If a plain pattern explains the domain poorly but the "tokens + short suffix"
        # style explains it well, the addresses carry name parts we do not have.
        suffix = _suffix_style_hits(pairs)
        if len(pairs) >= 3 and suffix >= 0.6 and suffix > model.confidence:
            model.predictable = False
            model.confidence = suffix
            model.style_note = (f'{suffix:.0%} of addresses are name-tokens plus a short '
                                'suffix (initials of given names not held) - full legal '
                                'name required, cannot be generated')
        models[domain] = model
    return models


def firm_domains(contacts: list[dict]) -> dict[str, str]:
    """Map each firm to the domain most of its people actually use."""
    counts: dict[str, Counter] = defaultdict(Counter)
    for c in contacts:
        email = (c.get('email') or '').strip().lower()
        firm = (c.get('firm') or '').strip()
        if '@' in email and firm:
            domain = email.split('@')[1]
            if domain not in FREE_MAIL:
                counts[firm][domain] += 1
    return {firm: c.most_common(1)[0][0] for firm, c in counts.items() if c}


def cross_validate(contacts: list[dict]) -> dict[str, dict]:
    """Leave-one-out accuracy per domain.

    For every known address, relearn the pattern without it and check whether the
    remaining evidence predicts it. This is the honest measure of how often a
    generated address will be right.
    """
    by_domain: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for c in contacts:
        email = (c.get('email') or '').strip().lower()
        if '@' not in email:
            continue
        local, _, domain = email.partition('@')
        if domain in FREE_MAIL or is_role_account(local):
            continue
        by_domain[domain].append((c.get('name', ''), local))

    report = {}
    for domain, pairs in by_domain.items():
        if len(pairs) < 3:
            report[domain] = {'n': len(pairs), 'correct': None, 'accuracy': None}
            continue
        correct = 0
        for i in range(len(pairs)):
            held_name, held_local = pairs[i]
            rest = pairs[:i] + pairs[i + 1:]
            scored = _score_patterns(rest)
            if not scored or scored[0][1] == 0:
                continue
            got = PATTERNS[scored[0][0]](name_tokens(held_name))
            correct += (got == held_local)
        report[domain] = {'n': len(pairs), 'correct': correct,
                          'accuracy': correct / len(pairs)}
    return report
