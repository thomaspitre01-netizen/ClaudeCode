# Japan property database (Phase One)

A private research database of houses, land and old buildings for sale in Greater
Tokyo and Greater Kamakura. It collects listings from several Japanese sources,
keeps the original Japanese next to structured English fields, merges the same
property seen on different sites, and records every price change and removal.
There is no website yet: this is the data layer a dashboard will sit on.

## Quick start

```bash
pip install -r japan_re/requirements.txt   # without PyPI access, requests alone is enough:
                                          # a stdlib HTML reader stands in for beautifulsoup4
export JRE_CONTACT=you@example.com        # goes in the User-Agent so sites can reach you

python -m japan_re sources -v             # what is crawled, and why or why not
python -m japan_re crawl                  # core areas: Chuo Line corridor + Kamakura/Zushi/Hayama
python -m japan_re crawl --tier tokyo     # all of Tokyo too
python -m japan_re geocode                # map pins for listings that did not publish any
python -m japan_re translate              # English descriptions (needs ANTHROPIC_API_KEY)
python -m japan_re stats
```

The database is `data/japan_re.sqlite`; raw pages are kept gzipped under `data/raw/`
so parsers can be improved and re-run without fetching again. Neither is committed.

Crawls are deliberately slow: one request every 6+ seconds per site (longer if the
site asks), so a first full crawl of the core areas takes hours, not minutes.
After that, only new listings and ones not read for 3 days are fetched.
To keep it fresh, run it daily, e.g. with cron:

```
30 4 * * *  cd ~/claudecode && python -m japan_re crawl && python -m japan_re geocode && python -m japan_re translate
```

## Using the data

```bash
python -m japan_re search --max-price 50M --min-land 200 --condition major_renovation
python -m japan_re search --type kominka --type traditional_house --area Kamakura --area Zushi
python -m japan_re search --station Kichijoji --walk 15 --built-before 1980 --sort ppm
python -m japan_re leads                  # the curated short list (≤¥70M; land, age, character, renovation first)
python -m japan_re leads --area Koenji --watchlist
python -m japan_re leads --out leads.md   # the whole Leads page: cards, indicators, categories, watchlist
python -m japan_re leads --out leads.json --format json   # the same for the dashboard
python -m japan_re show 123               # one property: all sources, price history, JA + EN text
python -m japan_re mark seen 123 124       # checked it; 'liked' also makes it a favorite, 'passed' hides it from Leads
python -m japan_re fav add 123 --note "big garden"
python -m japan_re reno 123 --low 35M --high 50M     # prints acquisition + renovation = total
python -m japan_re events --days 7        # new listings, price cuts, removals: what alerts will send
python -m japan_re export --format csv    # v_properties for Excel / a dashboard
```

A search result reads like the brief asked:

```
#3  ¥38.5M · Kamakura · kominka · 412 m² land · 118 m² building · 15 min walk (Kita-Kamakura) · ¥93k/m² land · full renovation
```

## How the data is organised

See `schema.sql`; the short version:

| Table | One row per |
|---|---|
| `listings` | advertisement (URL on a source): ~70 structured fields, `description_ja` / `description_en`, and `raw_fields_json` holding every label/value on the page verbatim |
| `properties` | physical property; listings point at it after duplicate detection. Holds your renovation estimate and notes |
| `price_history`, `listing_events` | every price change, new listing, removal, relisting, agency change and merge, with dates |
| `listing_stations` | line, station (JA + EN), walk and bus minutes |
| `favorites`, `dedup_matches`, `crawl_runs`, `snapshots` | as named |
| `v_properties` (view) | one row per property with price, ¥/m² land and building, land-to-building ratio, age, nearest station, estimated acquisition cost, source count, favorite flag: the table a dashboard reads |

Prices are integer JPY throughout; nothing is converted.

**Property types:** detached_house, traditional_house, kominka, machiya, apartment,
condominium, entire_building, land, mixed_use, commercial, other.
**Condition:** move_in_ready, minor_renovation, major_renovation, full_renovation,
derelict_rebuild, unknown. Both are set from the listing's own words, and the
Japanese that set them is stored (`property_type_evidence`, `condition_evidence`),
so "major renovation" can always be traced to e.g. 現況渡し or 要リフォーム.
Renovation need is never used to hide a property.

**Duplicates** (`dedup.py`): listings in the same municipality are scored on land
and building area (to 0.05 m²), construction year, town/chome, price and
coordinates. A land area that differs by more than 1% vetoes the match, which keeps
neighbouring lots in one subdivision apart. The reasons are stored with each
match. `python -m japan_re unmerge <listing id>` splits a wrong merge for good.

**Removed listings:** a listing missing from two consecutive *complete* crawls of
its area is marked removed. A crawl interrupted by errors, robots rules or
`--max-details` never removes anything.

**Translation:** structured fields (zoning, structure, rights, stations, type) are
translated by lookup tables, with no model involved. Titles and descriptions are
translated by Claude (`JRE_TRANSLATE_MODEL`, default `claude-opus-5`), cached by
text hash so each description is paid for once. The Japanese is never overwritten.

## Sources and the rules they set

See [SOURCES.md](SOURCES.md). In short: robots.txt is always obeyed, a site that
answers 403 or a CAPTCHA is left alone for the rest of the run, and a source
whose terms forbid automated collection or translation is flagged and not crawled.

## Tests

```bash
python -m unittest discover tests
```

The fixtures in `tests/fixtures/` are synthetic pages shaped like real ones.
Once live pages are available, save a few (`File > Save Page As`) and load them
with `python -m japan_re import-html --source suumo page.html` to check the
parsers against reality.
