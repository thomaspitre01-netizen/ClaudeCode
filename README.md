# IFA Contact Database

An Excel contact database and dashboard for the IFA (independent financial adviser) network,
rebuilt from the original `IFA_Meeting_List.xlsx`.

## Files

| File | What it is |
|---|---|
| `IFA_Contacts_Dashboard.xlsx` | The workbook. Formula-driven — no macros needed. |
| `IFA_Contacts_Macros.bas` | Optional VBA module (add contact, sort, extend capacity, find duplicates). |
| `build/` | The Python that generated the workbook, so it can be rebuilt from the source file. |

## Tabs

1. **Dashboard** — headline numbers, contacts by firm, event participation, engagement mix,
   which source list each contact came from, plus charts.
2. **Meeting Stats** — meeting KPIs, activity by month, coverage by firm, and a
   "follow up first" list of the relationships that have gone coldest.
3. **Contacts** — the searchable directory. Five filter boxes at the top (firm, met, event
   attended, warmth, free-text search) rebuild the list instantly.
4. **RawData** — the single source of truth. Type into the white columns; the grey columns
   calculate themselves.
5. **Setup** — user guide, the events table, every dropdown list, and the documented
   assumptions behind the migration.
6. **Src – …** — the five original tabs, unchanged, kept for reference. No formula reads them.

## Adding a contact

Open **RawData**, go to the first empty row, type into columns B–S. Everything else updates.

## Adding an event

Open **Setup**, fill a free row of the EVENTS table (name / short name / date). A new status
column appears in RawData and a new line appears on the Dashboard's event table.

## Rebuilding from source

```bash
pip install openpyxl
python build/prep.py      # source.xlsx  -> contacts.json
python build/build.py     # contacts.json -> IFA_Contacts_Dashboard.xlsx
```
