"""Deliverability checks that stop short of probing anyone's mail server.

Two levels are worth distinguishing:

  syntax + MX   - the address is well formed and its domain publishes a mail exchanger.
                  Cheap, invisible to the recipient, and catches dead domains and typos.
                  This is what the tool does.

  SMTP RCPT     - opening a session with the recipient's mail server and asking whether
                  the mailbox exists. This is NOT done here. It is what gets a sending IP
                  greylisted or blacklisted, most providers lie about the answer anyway
                  (catch-all domains accept everything), and a burst of probes against a
                  firm's server is exactly the behaviour their security team alerts on.

So a generated address that passes here is "plausible and the domain accepts mail",
never "confirmed to exist". Treat the first send as the real test and watch the bounces.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import dns.exception
import dns.resolver

from .patterns import FREE_MAIL, is_role_account

SYNTAX = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')

DISPOSABLE = {
    'mailinator.com', 'guerrillamail.com', '10minutemail.com', 'tempmail.com',
    'trashmail.com', 'yopmail.com', 'sharklasers.com', 'throwawaymail.com',
}

_mx_cache: dict[str, bool] = {}


@dataclass
class Check:
    email: str
    syntax_ok: bool
    domain_has_mx: bool | None      # None = lookup could not be completed
    is_role: bool
    is_free_mail: bool
    is_disposable: bool

    @property
    def sendable(self) -> bool:
        return bool(self.syntax_ok and self.domain_has_mx and not self.is_disposable)

    @property
    def note(self) -> str:
        if not self.syntax_ok:
            return 'malformed'
        if self.is_disposable:
            return 'disposable domain'
        if self.domain_has_mx is False:
            return 'domain accepts no mail'
        if self.domain_has_mx is None:
            return 'MX lookup failed'
        if self.is_role:
            return 'role account (a desk, not a person)'
        if self.is_free_mail:
            return 'personal free mailbox'
        return 'ok'


def has_mx(domain: str, timeout: float = 5.0) -> bool | None:
    domain = domain.lower()
    if domain in _mx_cache:
        return _mx_cache[domain]
    resolver = dns.resolver.Resolver()
    resolver.lifetime = resolver.timeout = timeout
    result: bool | None
    try:
        result = len(resolver.resolve(domain, 'MX')) > 0
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        try:
            # a bare A record still accepts mail under RFC 5321 fallback
            result = len(resolver.resolve(domain, 'A')) > 0
        except dns.exception.DNSException:
            result = False
    except dns.exception.DNSException:
        result = None
    _mx_cache[domain] = result
    return result


def check(email: str, do_dns: bool = True) -> Check:
    email = (email or '').strip().lower()
    ok = bool(SYNTAX.match(email))
    local, _, domain = email.partition('@')
    return Check(
        email=email,
        syntax_ok=ok,
        domain_has_mx=has_mx(domain) if (ok and do_dns) else (None if ok else False),
        is_role=ok and is_role_account(local),
        is_free_mail=domain in FREE_MAIL,
        is_disposable=domain in DISPOSABLE,
    )
