# IFA email toolkit

Finds and fills in email addresses for Singapore IFA contacts, feeding straight back
into `IFA_Contacts_Dashboard.xlsx`.

```bash
pip install requests beautifulsoup4 lxml dnspython openpyxl

python -m ifa_emails patterns                 # what format each firm uses
python -m ifa_emails predict --validate       # fill the blanks, with confidence
python -m ifa_emails crawl --sites ifa_emails/sites.txt --operator you@firm.com
python -m ifa_emails export                   # one CSV shaped like RawData
```

## Read this before you trust the output

**The crawler is the small half.** Singapore IFA firms do not publish their advisers'
addresses. A live run over ippfa.com, gyc.com.sg and finexis.com.sg returned five
addresses, *all* of them desks — `enquiries@`, `pdpa@`, `marketconduct@`. Zero named
advisers. That is the norm, not a failure of the crawler, and it is why your existing
list came from events and meetings rather than the web. Use `crawl` to confirm a
domain and pick up branch contacts; do not expect a roster from it.

**The pattern engine is the big half.** Your 253 known addresses reveal each firm's
house format, which fills in the people you have a name for but no address:

| domain | known | format | holdout accuracy |
|---|---|---|---|
| proinvest.com.sg (PIAS) | 91 | `allgiven.surname` | 95% |
| infinityfa.com.sg | 12 | `allgiven.surname` | 92% |
| manulifefa.com.sg | 36 | `allgiven.surname` | 86% |
| synergy.com.sg | 29 | `allgivensurname` | 83% |
| ifastgm.com | 6 | `allgiven.surname` | 83% |
| finexis.com.sg | 11 | `first.last` | 82% |
| fapl.sg (Financial Alliance) | 19 | `firstlast` | 79% |
| promiseland.com.sg | 4 | `allgiven.surname` | 75% |
| singlife.com, fa.sg | 5, 4 | inconsistent | reported, not guessed |
| **phillip.com.sg, awfa.com.sg** | 20, 3 | **not predictable** | 15%, 0% |

Accuracy is leave-one-out: each known address is predicted from a format learned on
the *other* addresses at that domain, so these are out-of-sample numbers, not a fit.

**Two places it refuses to guess, on purpose.**

*Phillip Capital* appends the initials of given names you do not hold — `Isabelle Tee
Ying Zi` becomes `isabelleteeyz`. The style is detected and reported; it cannot be
generated from a truncated name. Get those from a business card.

*Multi-part names* are the weak spot everywhere. Measured on your data, a learned
format reproduces **83% of two-token names but only 27% of three-token ones**, because
firms are inconsistent about exactly these: PIAS turned `Stella Sophia Goh` into
`stellasophia.goh` but `Paul See Hock Soon` into `paul.see`. Any name over two tokens
therefore drops below the confidence bar and lands in
`predicted_emails_needs_manual.csv` with its two or three candidate forms listed, for
you to pick from or verify.

On your current database that splits **116 missing addresses** into 37 worth sending
to and 79 to resolve by hand — deliberately conservative, because a wrong address
costs you a bounce and some sender reputation.

**Nothing here is verified.** `--validate` confirms the domain accepts mail (MX
lookup). It does not confirm the mailbox exists. The tool will not do SMTP `RCPT`
probing: providers lie about the answer on catch-all domains, and a burst of probes at
a firm's mail server is what gets a sending IP blacklisted. Your first send is the real
test — start with the highest-confidence rows and read the bounce report.

## How the crawler behaves

`robots.txt` fetched and obeyed · one request at a time per domain with a delay
(a declared `Crawl-delay` wins) · a page budget per site · same-site only · a
User-Agent carrying your address so a webmaster can reach you. There is an
`--ignore-robots` flag; it is hidden from `--help` and using it is your call, not the
tool's default.

**It does not touch LinkedIn.** LinkedIn's terms prohibit scraping, they enforce it,
and an account ban would cost you more than the addresses are worth.

**MAS's Register of Representatives is not scraped either.** It is the authoritative
list of licensed reps, but it sits behind reCAPTCHA and anti-forgery tokens; getting
past that means defeating bot protection. Search it by hand at
`eservices.mas.gov.sg/rr` — it gives you names and principal firms, and the pattern
engine turns those into addresses.

## Before you send

Not legal advice — points to put to whoever owns compliance, since you are a regulated
firm marketing to licensed intermediaries.

- **PDPA, business contact information.** Section 4(5) excludes an individual's
  business email from most Data Protection obligations when the individual *provided*
  it for a business purpose. Worth noting: an address this tool *generated* was never
  provided by anyone, so the carve-out is a weaker fit for predictions than for
  addresses somebody handed you. That distinction is exactly why the `Source` column
  records which is which.
- **Spam Control Act.** Unsolicited commercial email sent in bulk needs a working
  unsubscribe facility, honoured within the statutory window, accurate sender details,
  a non-misleading subject, and the `<ADV>` prefix.
- **Do Not Call** covers phone, SMS and fax — not email.
- **Financial Advisers Act.** Restrictions on unsolicited marketing of certain
  investment products can reach email. Confirm how they apply when the recipient is a
  licensed FA representative.
- **Practical, and the one that bites first:** bouncing a batch of guessed addresses
  damages your sending domain's reputation. Send the 37 high-confidence rows, watch
  what bounces, then decide about the rest.

## Files

| file | what it does |
|---|---|
| `patterns.py` | learns house formats, Singapore surname parsing, confidence scoring |
| `crawl.py` | the polite crawler and the address extractor |
| `validate.py` | syntax, MX, role/free/disposable classification |
| `cli.py` | the four sub-commands |
| `sites.txt` | seed list of firm websites |
