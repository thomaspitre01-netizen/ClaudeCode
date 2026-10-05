"""The source registry: every site the crawler knows about, and what it may do there.

POLICIES - decided per source from its robots.txt and terms of use, and recorded
in SOURCES.md with the clause that decided it:

  allowed            no terms found that prohibit automated reading; robots.txt obeyed
  personal_use_only  terms allow use only within private, personal use (Japanese
                     Copyright Act art. 30). Fine for a private research tool; the
                     data must never be republished from this database
  unverified         terms could not be read; not crawled until someone reads them
  restricted         terms prohibit copying/translating/reusing content without
                     permission; flagged, never crawled
  forbidden          terms or robots.txt forbid automated access outright; never crawled

Only 'allowed' and 'personal_use_only' sources can be crawled. There is no
command-line switch that crawls a restricted source: changing a policy means
editing this file, with the reason written next to it.
"""
from __future__ import annotations

from .base import Source
from .portals import Athome, Homes, Suumo
from .specialists import Ieichiba, RealKamakura, RealTokyo

CRAWLABLE = ('allowed', 'personal_use_only')

REGISTRY: dict[str, Source] = {s.id: s for s in (
    Suumo(), Athome(), Homes(), RealKamakura(), RealTokyo(), Ieichiba(),
)}


def get(source_id: str) -> Source:
    return REGISTRY[source_id]


def crawlable(source: Source) -> bool:
    return source.policy in CRAWLABLE
