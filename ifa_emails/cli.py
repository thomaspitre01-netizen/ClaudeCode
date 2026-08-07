"""Command line for the IFA email toolkit.

    python -m ifa_emails patterns                  what format each firm uses, and how well it holds up
    python -m ifa_emails predict                   fill the missing addresses, with confidence
    python -m ifa_emails crawl --sites sites.txt   what the firms' own websites publish
    python -m ifa_emails export                    one CSV, ready to paste into RawData

Contacts are read straight out of the workbook's RawData tab, so the toolkit always
works from the same source of truth as the dashboard.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from . import patterns as P
from . import validate as V
from .crawl import crawl_site

WORKBOOK = 'IFA_Contacts_Dashboard.xlsx'


# --------------------------------------------------------------------------- io
def load_contacts(path: str) -> list[dict]:
    """Read Name / Email / Firm / Contact Type out of the workbook's RawData tab."""
    if path.endswith('.json'):
        return json.load(open(path))
    import openpyxl
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True)['RawData']
    out = []
    for row in ws.iter_rows(min_row=2, max_col=6, values_only=True):
        if not row[1]:
            continue
        out.append({'name': str(row[1]).strip(),
                    'email': str(row[2] or '').strip(),
                    'firm': str(row[3] or '').strip(),
                    'ctype': str(row[4] or '').strip(),
                    'source': str(row[5] or '').strip()})
    return out


def write_csv(path: str, rows: list[dict], fields: list[str]) -> None:
    with open(path, 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    print(f'  wrote {len(rows)} rows -> {path}')


# ---------------------------------------------------------------- sub-commands
def cmd_patterns(args) -> int:
    contacts = load_contacts(args.contacts)
    models = P.learn(contacts)
    cv = P.cross_validate(contacts)

    print(f'\n{len(contacts)} contacts, '
          f'{sum(1 for c in contacts if "@" in c["email"])} with an address\n')
    print(f'{"domain":26}{"known":>6} {"house format":16}{"fit":>6}{"holdout":>9}  verdict')
    print('-' * 96)
    tot = cor = 0
    for d, m in sorted(models.items(), key=lambda kv: -kv[1].samples):
        c = cv.get(d, {})
        acc = f'{c["accuracy"]:.0%}' if c.get('accuracy') is not None else '-'
        print(f'{d:26}{m.samples:>6} {str(m.pattern or "-"):16}'
              f'{m.confidence:>5.0%}{acc:>9}  {m.verdict(args.min_confidence)}')
        if m.style_note:
            print(f'{"":26}       ^ {m.style_note}')
        if c.get('accuracy') is not None:
            tot += c['n']
            cor += c['correct']
    if tot:
        print('-' * 96)
        print(f'leave-one-out accuracy across domains with 3+ known addresses: '
              f'{cor}/{tot} = {cor / tot:.1%}')
    return 0


def cmd_predict(args) -> int:
    contacts = load_contacts(args.contacts)
    models = P.learn(contacts)
    domains = P.firm_domains(contacts)

    rows, skipped = [], []
    for c in contacts:
        if '@' in c['email'] or not c['name']:
            continue
        domain = domains.get(c['firm'])
        if not domain:
            skipped.append((c['name'], c['firm'], 'no known domain for this firm'))
            continue
        m = models[domain]
        verdict = m.verdict(args.min_confidence)
        conf = m.row_confidence(c['name'])
        alts = m.alternatives(c['name'], k=3)
        guess = m.predict(c['name'])

        if verdict != 'predict' or conf < args.min_confidence or not guess:
            why = verdict if verdict != 'predict' else (
                'multi-part name - the firm is inconsistent about these'
                if len(P.name_tokens(c['name'])) > 2 else 'below confidence threshold')
            if not guess:
                why = 'name too short to apply the format'
            candidates = ([guess] if guess else []) + alts
            skipped.append((c['name'], c['firm'],
                            why + (f' (candidates: {", ".join(candidates[:3])})' if candidates else '')))
            continue
        rows.append({'Name': c['name'], 'Firm': c['firm'], 'Predicted Email': guess,
                     'Pattern': m.pattern, 'Confidence': f'{conf:.0%}',
                     'Evidence (known addresses)': m.samples,
                     'Alternatives': ' | '.join(alts[:2]),
                     'Verified': '', 'Status': 'unverified prediction'})

    if args.validate and rows:
        print(f'  checking {len({r["Predicted Email"].split("@")[1] for r in rows})} domains for MX...')
        for r in rows:
            r['Status'] = V.check(r['Predicted Email']).note

    rows.sort(key=lambda r: (-int(r['Confidence'].rstrip('%')), r['Firm'], r['Name']))
    write_csv(args.out, rows, ['Name', 'Firm', 'Predicted Email', 'Pattern', 'Confidence',
                               'Evidence (known addresses)', 'Alternatives', 'Verified', 'Status'])
    if skipped:
        write_csv(args.out.replace('.csv', '_needs_manual.csv'),
                  [{'Name': n, 'Firm': f, 'Why': w} for n, f, w in skipped],
                  ['Name', 'Firm', 'Why'])
    print(f'\n  {len(rows)} predicted at >= {args.min_confidence:.0%} confidence, '
          f'{len(skipped)} need a verified source (see the _needs_manual file - it '
          f'lists the candidate forms for each).')
    print('  Nothing here is confirmed. Send to the high-confidence rows first and '
          'watch the bounce report.')
    return 0


def cmd_crawl(args) -> int:
    seeds = [ln.strip() for ln in Path(args.sites).read_text().splitlines()
             if ln.strip() and not ln.startswith('#')]
    all_rows = []
    for seed in seeds:
        print(f'\n  {seed}')
        rep = crawl_site(seed, operator_email=args.operator, max_pages=args.max_pages,
                         delay=args.delay, obey_robots=not args.ignore_robots,
                         verbose=args.verbose)
        if rep.error and not rep.hits:
            print(f'    no data ({rep.error})')
        personal = [h for h in rep.hits if not h.is_role]
        print(f'    {rep.pages_fetched} pages, {rep.pages_blocked_by_robots} skipped by robots, '
              f'{len(rep.hits)} addresses ({len(personal)} look personal)')
        for h in rep.hits:
            all_rows.append({'Email': h.email, 'Name found nearby': h.nearby_name,
                             'Domain': h.domain, 'Kind': 'role' if h.is_role else 'personal',
                             'Found on': h.source_url, 'Seed': seed})

    if args.validate and all_rows:
        for r in all_rows:
            r['Status'] = V.check(r['Email']).note

    write_csv(args.out, all_rows, ['Email', 'Name found nearby', 'Domain', 'Kind',
                                   'Status', 'Found on', 'Seed'])
    return 0


def cmd_export(args) -> int:
    """Merge predictions and crawl output into RawData's own column order."""
    contacts = load_contacts(args.contacts)
    known = {(c['email'] or '').lower() for c in contacts if '@' in c['email']}
    by_name = {P.name_tokens(c['name']) and ''.join(P.name_tokens(c['name'])): c
               for c in contacts}

    out, seen = [], set()
    for path, source in [(args.predictions, 'Pattern prediction'), (args.crawled, 'Website')]:
        if not path or not Path(path).exists():
            continue
        for row in csv.DictReader(open(path, encoding='utf-8-sig')):
            email = (row.get('Predicted Email') or row.get('Email') or '').lower().strip()
            if not email or email in known or email in seen:
                continue
            if (row.get('Status') or 'ok') not in ('ok', 'unverified prediction', ''):
                continue
            seen.add(email)
            name = row.get('Name') or row.get('Name found nearby') or ''
            key = ''.join(P.name_tokens(name))
            existing = by_name.get(key) if key else None
            out.append({
                'Name': name or email.split('@')[0],
                'Email': email,
                'Firm': row.get('Firm') or (existing or {}).get('firm') or '',
                'Contact Type': (existing or {}).get('ctype') or 'Adviser',
                'Source': source,
                'Met?': 'No', 'Invested?': 'No',
                'Notes': (f"{source}; confidence {row.get('Confidence')}"
                          if row.get('Confidence') else f"{source}: {row.get('Found on','')}")[:250],
                'Already in database': 'yes - fills a blank email' if existing else 'no - new contact',
            })

    write_csv(args.out, out, ['Name', 'Email', 'Firm', 'Contact Type', 'Source',
                              'Met?', 'Invested?', 'Notes', 'Already in database'])
    print('  Paste columns Name..Notes into the first empty RawData row; '
          'set the event columns to "Not Invited".')
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='ifa_emails', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--contacts', default=WORKBOOK,
                    help='workbook (reads the RawData tab) or a contacts .json')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('patterns', help='show each firm house format and its accuracy')
    p.add_argument('--min-confidence', type=float, default=0.70)
    p.set_defaults(func=cmd_patterns)

    p = sub.add_parser('predict', help='generate the missing addresses')
    p.add_argument('--min-confidence', type=float, default=0.70,
                   help='below this a domain is reported, not guessed (default 0.70)')
    p.add_argument('--validate', action='store_true', help='also check MX records')
    p.add_argument('--out', default='predicted_emails.csv')
    p.set_defaults(func=cmd_predict)

    p = sub.add_parser('crawl', help='collect what firm websites publish')
    p.add_argument('--sites', required=True, help='text file, one site per line')
    p.add_argument('--operator', required=True,
                   help='your email - goes in the User-Agent so webmasters can reach you')
    p.add_argument('--max-pages', type=int, default=40)
    p.add_argument('--delay', type=float, default=2.0, help='seconds between requests')
    p.add_argument('--ignore-robots', action='store_true',
                   help=argparse.SUPPRESS)     # available, but you own the consequences
    p.add_argument('--validate', action='store_true')
    p.add_argument('--verbose', action='store_true')
    p.add_argument('--out', default='crawled_emails.csv')
    p.set_defaults(func=cmd_crawl)

    p = sub.add_parser('export', help='merge into a RawData-shaped CSV')
    p.add_argument('--predictions', default='predicted_emails.csv')
    p.add_argument('--crawled', default='crawled_emails.csv')
    p.add_argument('--out', default='to_add_to_rawdata.csv')
    p.set_defaults(func=cmd_export)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
