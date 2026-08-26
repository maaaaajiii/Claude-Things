You are refreshing the manually-researched half of the macro dashboard. The automated half
(39 FRED series plus CoinGecko) is pulled by a separate script and is NOT your job. Your job is
only the data that cannot be fetched programmatically from this machine.

Your entire output is a rewrite of `macro-dashboard/macro_manual.json`.

## Absolute rules

1. **Never invent a number.** If a search does not give you a figure you can attribute, keep the
   previous value and leave its old `as_of` date untouched so the dashboard flags it as stale.
   A visibly stale number is correct behaviour. A fabricated fresh one is the single worst thing
   you can do to this file.
2. **Every block you update must get today's date in `as_of`** and at least one working URL in
   `sources`. If you did not verify it today, do not move the date.
3. **Keep the JSON schema exactly as it is.** Same keys, same nesting, same types. The builder
   reads it directly and will break on a shape change. Do not add or rename keys.
4. **Fed probabilities are quoted as a range, never as a single point.** CME FedWatch is blocked
   from this machine and prediction venues routinely disagree by 10-20 points on the same day.
   Fill `pct` with your best central estimate and `range` with the actual spread you observed
   across sources. If sources disagree wildly, widen the range rather than picking a favourite.
5. Write valid UTF-8 JSON. No trailing commas. No comments except the existing `_README` key.

## What to refresh

**`fed_odds`** · odds for the next FOMC decision. Check Polymarket
(`https://polymarket.com/event/fed-decision-in-september-762` or the current equivalent) and any
press reporting of CME FedWatch numbers. Update `meeting` if the next meeting has changed.
Search terms that work: "FOMC [month] 2026 rate decision odds", "fed rate hike probability".

**`calendar`** · forward-looking economic events. Remove only events dated **strictly before
today**. **Keep an event dated today**, even if you believe it has already happened. Most US
releases land at 08:30 ET, which is 19:30 WIB, so an event dated today is usually still in the
future for the reader in Jakarta, and the dashboard renders it as "hari ini". Deleting it early
removes the single most useful row on the page. Add new
ones so the list always runs at least 6 weeks ahead. Keep the high-impact ones: CPI, PCE, NFP,
FOMC (note which meetings publish a dot plot), Jackson Hole, and the Quarterly Refunding
Announcement. For each event write `why` in Indonesian, explaining to a beginner why that
release matters for risk assets. Confirm dates against the official source where you can:
`bls.gov/schedule/news_release/`, `bea.gov`, `federalreserve.gov/monetarypolicy/fomccalendars.htm`,
`home.treasury.gov/policy-issues/financing-the-government/quarterly-refunding`.

**`crypto_positioning`** · ETF flows, futures open interest, funding rates, and 24h liquidations.
Search for the most recent daily figures. Set `verdict` per item to exactly one of
`good` / `bad` / `neutral`, judged as the effect on risk appetite, and write `why` in Indonesian.
This block goes stale in 3 days, so it matters that the date is honest.

**`bi`** · the Bank Indonesia policy rate. RDG meets monthly. Check whether a newer decision has
landed than the `as_of` in the file. Indonesian sources are fine and preferred here.

## Language

All human-readable text in the file (`why`, `note`, `label`) is written in **Indonesian**, aimed
at a reader who is still learning macro. Plain words, short sentences, explain the mechanism
rather than naming it. Do not use em dashes anywhere; use commas, periods, or "·".

## When you are done

Write the file. Do not run the dashboard builder, do not touch any other file in the vault, and
do not create wiki pages or log entries. The PowerShell wrapper runs the builder immediately
after you exit, and it will run whether you succeeded or failed.

Finish by printing a single line in this exact format so the wrapper can record it:

```
MACRO_REFRESH_OK <what you updated, comma separated>
```

If you could not verify anything at all, print instead:

```
MACRO_REFRESH_NONE <one-line reason>
```
