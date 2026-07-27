# Mason Family Calendar

An **unofficial** companion site that turns the Mason City Schools 2026–2027 academic
calendar into calendar subscriptions parents can add to their phones — plus optional
Mason High School varsity athletics.

Not affiliated with, endorsed by, or operated by Mason City Schools.

---

## What it produces

Static files in `dist/`, ready for GitHub Pages:

| Feed | Who it's for |
|---|---|
| `feeds/mecc.ics` | MECC, grades PK–2 |
| `feeds/mhs.ics` | Mason High School, grades 9–12 |
| `feeds/mhs-varsity.ics` | MHS academic calendar **+** all varsity athletics |
| `feeds/varsity-all.ics` | Varsity athletics only, all sports |
| `feeds/varsity-<sport>.ics` | One sport at a time (generated only for sports with games) |
| `feeds/district.ics` | District-wide dates only — for families with kids in several buildings |

Plus `index.html` (the subscribe flow) and `calendar.json` (data the page reads).

Mason Elementary (3–4), Mason Intermediate (5–6) and Mason Middle School (7–8) are
already wired into the data model — flip `"published": true` in `data/schools.json`
and they get feeds and buttons with no code changes.

---

## First-time setup (about 10 minutes)

1. **Create the repo.** On GitHub, make a new *public* repository. Public is required
   for free GitHub Pages, and calendar apps need to fetch the feeds without auth anyway.

2. **Push this folder.**
   ```bash
   cd mason-family-calendar
   git init -b main
   git add .
   git commit -m "Mason Family Calendar: initial build"
   git remote add origin https://github.com/YOUR-USERNAME/mason-family-calendar.git
   git push -u origin main
   ```

3. **Turn on Pages.** Repo → **Settings → Pages → Build and deployment → Source:
   GitHub Actions**. Do this *before* the first workflow run, or the deploy step fails.

4. **Run the workflow.** Repo → **Actions → Build and publish calendar feeds → Run
   workflow**. It scrapes athletics, builds the feeds, validates them and publishes.

5. **Your site is live** at `https://YOUR-USERNAME.github.io/mason-family-calendar/`.

After that it rebuilds itself daily at 07:10 UTC (about 3am Eastern) and on every push.

### Custom domain (optional)

Point a `CNAME` record at `YOUR-USERNAME.github.io`, then set the domain under
**Settings → Pages → Custom domain**. Add a `site/CNAME` file containing the domain
so it survives rebuilds.

> **Pick the URL before you share it.** Calendar subscriptions are pinned to the
> address people subscribed with. Moving the site later silently breaks every
> existing subscription — they keep showing stale data rather than erroring.

---

## Running it locally

```bash
pip install -r requirements.txt

python scripts/scrape_sports.py            # optional; needs network
python scripts/build.py --base-url http://localhost:8000
python scripts/validate.py
python scripts/test_parser.py

python -m http.server 8000 --directory dist
```

The site derives subscribe links from the URL it is actually served from, so the
`--base-url` value only affects the `URL:` property written inside each `.ics`.

---

## How the data gets in

### Academic calendar — hand-transcribed, deliberately

`data/academic-2026-27.json` was transcribed by hand from the district's
*26|27 Academic Calendar* PDF (revised 7.8.25). The district publishes it as a
flattened image with no extractable text, so there is nothing to scrape. Every date
was cross-checked against the printed grid **and** the "Important Dates" legend.

To fix or add a date, edit that file and push. Fields:

- `start` / `end` — **inclusive** ISO dates; the ICS writer converts `end` to the
  exclusive `DTEND` that RFC 5545 requires
- `audiences` — `["all"]`, or building codes from `data/schools.json`
- `byAudience` — per-building overrides for `summary` / `description`
- `category` — drives the colour dot on the site

### Athletics — scraped daily

`scripts/scrape_sports.py` walks <https://www.gomasoncomets.com/schedules/>, finds
every schedule PDF, and parses the game rows out of them. There is no ICS, RSS or
JSON feed on the athletics site — PDFs are all there is.

It filters to the season window (`2026-08-01` … `2027-07-31`) so last season's PDFs,
which stay posted until the new ones go up, never leak into the feed.

**As of July 2026 the athletics site still had only 2025-26 schedules posted.** That
is expected this time of year. The sports feeds publish valid-but-nearly-empty, carrying
one explanatory event, and fill themselves in within a day of Mason posting the new
PDFs. Nobody has to re-subscribe.

If the scraper misses something or a game gets moved, add it to
`data/sports-manual.json` — manual entries override scraped ones with the same
sport + level + gender + date + opponent.

To include JV and freshman schedules, change `--levels Varsity` to
`--levels Varsity,JV,Freshman` in `.github/workflows/deploy.yml`.

---

## Layout

```
data/
  academic-2026-27.json   hand-transcribed district calendar (source of truth)
  schools.json            buildings, grade bands, which ones are published
  sports-manual.json      hand-entered games; override the scraper here
  sports-scraped.json     generated by the scraper, not committed
scripts/
  ics.py                  dependency-free RFC 5545 writer
  build.py                turns the data into dist/
  scrape_sports.py        athletics PDF scraper
  validate.py             CI gate: refuses to publish malformed feeds
  test_parser.py          unit tests for the parser and the ICS writer
site/                     the static site, copied verbatim into dist/
.github/workflows/        daily rebuild and Pages deploy
```

---

## Notes on correctness

Things that quietly break calendar feeds, and how they're handled here:

- **`DTEND` is exclusive.** A one-day event on Aug 13 ends Aug 14. Getting this wrong
  is the single most common ICS bug; there's a test for it.
- **Lines fold at 75 *octets*, not characters.** Em dashes are three bytes in UTF-8.
  `fold()` never splits a multi-byte sequence, and `validate.py` fails the build if
  any line exceeds 75 octets.
- **CRLF everywhere.** Bare `\n` breaks strict parsers. Checked in CI.
- **Stable UIDs.** Derived by hash from the event's identity, so rebuilding updates
  events in place instead of creating duplicates in people's calendars.
- **An embedded `VTIMEZONE`.** Outlook desktop won't resolve a bare `TZID`, so game
  start times would drift. Emitted only when the feed actually contains timed events.
- **Empty feeds carry one event.** Google treats a zero-event subscription as a broken
  URL and drops it silently.

### One discrepancy worth knowing about

On the district PDF, **Friday March 12, 2027** is shaded as *both* a Journey Day and a
professional work day, but the printed legend lists it only under Journey Days. Either
way there's no school. It's recorded as a Journey Day with a note in the event
description. Worth a confirmation with the district.

---

## Contributing a correction

Open an issue with the date and what's wrong, or edit `data/academic-2026-27.json`
and open a pull request. The district's published calendar always wins.
