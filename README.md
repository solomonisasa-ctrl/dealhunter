# Deal Hunter

A personal tool that watches Reddit, eBay, and Etsy for underpriced collectibles
(starting with watches), scores each new listing with Claude (deal score +
resale liquidity), and pushes an ntfy.sh alert when something qualifies.
Runs on a schedule via GitHub Actions - no server to maintain - with a local
dashboard for browsing findings and editing your watchlist.

## Architecture at a glance

- `config/` - credentials-free configuration: `settings.py` (loads env
  vars/secrets), `watchlist.yaml` (your plain-English hunts), `categories.yaml`
  (pluggable category definitions - currently just `watches`).
- `src/dealhunter/` - core logic. No hardcoded personal values; everything
  reads from `config/`.
  - `sources/` - one adapter per marketplace, behind a common interface.
  - `analysis/` - `analyzer.py` (Claude call) + `scoring.py` (pure,
    deterministic, unit-tested deal score / liquidity math).
  - `storage/` - JSON-file state, findings history, health history.
  - `pipeline.py` - wires it all together for one hunt run.
- `scripts/run_hunt.py` - entrypoint GitHub Actions calls.
- `scripts/dry_run.py` - self-test against `fixtures/sample_listings.json`,
  no real API calls to Reddit/eBay, no state mutation.
- `dashboard/` - local FastAPI app + static HTML/JS/CSS (feed, detail view,
  watchlist editor, status header).
- `.github/workflows/hunt.yml` - scheduled run; commits `data/` back to the
  repo so the dashboard has something to read after a `git pull`.

**Known v1 limitation:** eBay's Marketplace Insights API (real sold-listing
data) requires selective eBay approval. Until/unless you get that access,
`ebay_source.py` uses active-listing counts as a liquidity *proxy* - clearly
labeled as such wherever it shows up.

## 1. Accounts & credentials you'll need

| Service | What to do | You'll get |
|---|---|---|
| Reddit | Go to [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps), click "create app", choose type **script**, set redirect URI to `http://localhost:8080` (unused but required) | `client_id` (under the app name), `client_secret` |
| eBay | Register at [developer.ebay.com](https://developer.ebay.com), create a **Production** keyset under "Application Keys" | `Client ID` (App ID), `Client Secret` (Cert ID) |
| Etsy | Create an app at [etsy.com/developers/your-apps](https://www.etsy.com/developers/your-apps) | `Keystring`, `Shared secret` - public read endpoints only, no OAuth consent flow needed |
| Anthropic | Create a key at [console.anthropic.com](https://console.anthropic.com) | API key |
| ntfy.sh | No signup - just pick a hard-to-guess topic name, e.g. `dealhunter-xk92j`, and subscribe to it in the [ntfy app](https://ntfy.sh/app) (iOS/Android) or web | topic name |
| GitHub | Create a new **private** repo (this will hold your watchlist + finding history) | - |

You choose your own `REDDIT_USER_AGENT` string, e.g. `dealhunter/0.1 by u/yourusername` - Reddit just wants something identifiable, not generic.

## 2. Local setup

```bash
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

cp .env.example .env
# edit .env and fill in the 5 sets of credentials above
```

## 3. Run the tests (no network calls)

```bash
pytest
```

This runs `tests/test_scoring.py` etc against the pure scoring functions -
confirms the deal-score/liquidity math is correct before you trust it
against real data.

## 4. Dry run (sanity-check scoring against sample listings)

```bash
python scripts/dry_run.py
```

This calls Claude for real (needs `ANTHROPIC_API_KEY`) against the three
placeholder fixtures in `fixtures/sample_listings.json` (an Omega
Constellation, a Vostok, and your Grand Seiko Shunbun example) and prints
each one's deal score, liquidity rating, and full reasoning. **Replace the
placeholder listings with real ones you've hand-picked** to sanity-check
that the scores match your own judgment before going live - edit the JSON
file directly, the schema is documented inline via the `_note` fields.

## 5. Health check + a real (but manual) run

```bash
python scripts/run_hunt.py
```

This validates all 4 sets of credentials first (prints per-service
ok/error), then runs one full hunt across your watchlist against real
Reddit/eBay, writes results to `data/findings.json`, `data/state/`, and
`data/health.json`, and sends an ntfy push for anything that qualifies.
Start with just the `gs-shunbun` example item in `config/watchlist.yaml`
(or edit it to something narrower) so your first run doesn't fire off a lot
of Claude calls.

If it fails outright, you'll get an ntfy notification tagged "Deal Hunter
run failed" instead of silence.

## 6. Dashboard

```bash
uvicorn dashboard.server:app --reload --port 8420
```

Open http://127.0.0.1:8420 - you should see the finding(s) from step 5 in
the Feed tab, click one for the full reasoning, and use the Watchlist tab to
add/edit hunts (writes directly to `config/watchlist.yaml`). The status pill
in the header shows the last run's health at a glance.

The Watchlist tab shows a banner if you have local, unpushed changes to
`watchlist.yaml` - `git add`/`commit`/`push` those yourself when you're
ready; the dashboard never auto-commits or pushes on its own.

## 7. Deploy the scheduler

```bash
git push -u origin main   # or however you've set up your remote
```

Then in your GitHub repo: **Settings → Secrets and variables → Actions**,
add these repository secrets:

- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`
- `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`
- `ETSY_KEYSTRING`, `ETSY_SHARED_SECRET`
- `ANTHROPIC_API_KEY`
- `NTFY_TOPIC`

(`NTFY_SERVER` defaults to `https://ntfy.sh` - only add it as a repo
**variable**, not secret, if you're self-hosting ntfy.)

Then go to the **Actions** tab, select "Deal Hunter run", and click "Run
workflow" to trigger it manually the first time. Confirm it goes green and
that `data/` files show up as a new commit. After that it runs automatically
every 5 minutes (edit the cron in `.github/workflows/hunt.yml` to change
the cadence).

Pull those commits locally (`git pull`) whenever you want to check the
dashboard for fresh results.

## Adding a new hunt

Either use the dashboard's Watchlist tab, or edit `config/watchlist.yaml`
directly - it's documented inline. You only need `id`, `category`, and
`description`; everything else has a sensible default.

## Adding a new category later

Add a new top-level key to `config/categories.yaml` (subreddits, eBay
category IDs, structured fields to extract) - no code changes needed. The
core matching/scoring code has no "watches" hardcoded anywhere.
