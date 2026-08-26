# Macro Dashboard

A one-page read of macro conditions and what they mean for risk assets, in Indonesian.
Rebuilt automatically twice a day by `.github/workflows/macro-dashboard.yml`.

Output: `dashboard.html` in this folder.

## What it does

Pulls 39 series from FRED plus CoinGecko, computes the things nobody publishes (curve legs
per tenor, net liquidity, a rolling stock-bond correlation used as a regime detector), scores
each metric for what it means for risk assets, and writes a self-contained HTML page with a
generated conclusion for every section.

## Running it by hand

```bash
cd macro-dashboard
python build_macro_dashboard.py --verbose
```

Pure Python standard library. No `pip install`, no requirements file, no lockfile. That is a
deliberate constraint, not an accident: it means this runs unchanged on a laptop, in CI, or in
a cloud sandbox, and nothing rots when a dependency ships a breaking release.

## Layout detection

The same file works in two places and picks its paths automatically:

| Layout | Detected by | Output goes to |
|---|---|---|
| Vault | `../raw/` and `../index.md` exist | vault root, snapshots under `raw/macro-data-pulls/` |
| Flat | anything else, e.g. this repo | beside the script, snapshots in `./snapshots/` |

Override with `MACRO_OUT_DIR` and `MACRO_SNAP_DIR` if you need to.

There is deliberately no second copy of the builder. One file, two layouts, so a fix in one
place cannot silently fail to reach the other.

## Why snapshots are committed

`snapshots/*.json` records the latest official print date of every series on each run. The
"what changed since last refresh" panel works by diffing this run against the previous one.

Every delta on the page is anchored to **official print dates, not to refresh time**. If you
rebuild five times in a day and BLS published nothing, the CPI tile does not move. That is
correct behaviour, and the page says so. It only works if the previous snapshot survives, which
is why CI commits them back rather than letting the sandbox throw them away.

## The two halves, and why they are separate

**Automated half** · the 39 FRED series and CoinGecko. No credentials, no login, runs anywhere.

**Manual half** · `macro_manual.json` holds what cannot be fetched programmatically: the
economic calendar, Fed decision odds, crypto positioning, the Bank Indonesia rate. CME FedWatch
blocks automated clients outright, so those probabilities are quoted as a **range** across
venues rather than a point, because the venues routinely disagree by 10 to 20 points on the
same day.

Refreshing the manual half needs a browsing agent; `macro-refresh-prompt.md` is the instruction
set for it. The rules in that prompt matter more than the mechanics: **never invent a number**,
keep the old value *and its old date* when nothing can be verified, and let the page mark it
stale. A visibly stale number is correct. A fabricated fresh one is the worst thing that can
happen to this file.

Every block carries `as_of` and `stale_after_days`, so anything past its shelf life labels
itself BASI on the page instead of quietly pretending to be current.

## What this is not

A trading signal. Everything here is a reading aid. Macro-to-asset correlations are unstable,
flip sign across regimes, and are already priced by people with faster data.
