# Sources

Checked 27 September 2026. Policy values are defined in `sources/__init__.py`;
only `allowed` and `personal_use_only` sources are crawled, and changing a policy
means editing the source's class with the reason next to it.

## In the crawler

| Source | Kind | Policy | Crawled | Basis |
|---|---|---|---|---|
| SUUMO (suumo.jp) | national portal | personal_use_only | yes | Terms art. 2(1): no use beyond private use under the Copyright Act without Recruit's consent; art. 3(1)(6)(7): no interfering with the site, no commercial use. A private research database is private use; the data must not be republished. robots.txt disallows 300+ paths for all agents, enforced per URL. |
| 鎌倉R不動産 Real Kamakura Estate | specialist (old houses, character property) | allowed | yes | No robots.txt (404). No terms of use linked from the site, only a privacy policy. |
| 東京R不動産 Real Tokyo Estate | specialist | allowed | yes | No robots.txt (404). Same platform, no terms found. |
| 家いちば ieichiba.com | owner-to-buyer board (akiya, neglected houses) | allowed | yes | No robots.txt (404). No terms link on the board pages checked. Nationwide, so only the newest 15 board pages are read and out-of-area listings are stored as out of scope. |
| at home (athome.co.jp) | national portal | unverified | **no** | robots.txt has no rules for generic agents (only named bots), so it does not restrict this tool. The terms page refused automated reading (HTTP 405). Someone needs to read https://www.athome.co.jp/help/kiyaku.html in a browser; if it permits private use like SUUMO's, change the policy to personal_use_only. |
| LIFULL HOME'S (homes.co.jp) | national portal | restricted | **no** | Terms art. 6(1): no use, reproduction, adaptation, **translation**, reposting or distribution of site content without permission, except as the Copyright Act allows. Translation is the core of this tool, so it is flagged rather than crawled. |

## Not in the crawler

| Source | Why |
|---|---|
| REINS | Closed to licensed agents only. Not publicly accessible. |
| MLIT 不動産情報ライブラリ (reinfolib.mlit.go.jp) | Official API of past transaction prices, free with an API key. Not listings, but the right source for "price relative to local averages" in Phase Two. |
| Local agencies around Kamakura (e.g. kotokamakura.com, coco-h.com) and Chuo Line agencies | Next to add: each needs its listing index URL and a detail-link pattern, then a robots/terms check recorded here. See `sources/specialists.py` for the five-line template. |

## Rules the fetcher applies to every source

- robots.txt read first and obeyed, with `*` and `$` wildcards. If robots.txt cannot
  be reached, nothing is fetched from that host.
- One request at a time per host, at least 6 s apart, or the site's Crawl-delay.
- User-Agent `japan-re-research/0.1 (private property research; low-rate; contact: …)`.
- A 403 or CAPTCHA page stops that host for the run. No proxy, agent or header
  rotation, ever.
