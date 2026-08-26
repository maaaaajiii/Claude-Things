#!/usr/bin/env python3
"""
Build the macro dashboard at wiki/dashboard.html.

Design rules this script is built around, in order of importance:

1.  DELTA IS ANCHORED TO OFFICIAL PRINTS, NOT TO REFRESH TIME.
    Every "naik/turun" compares the latest official observation against the
    previous official observation of that same series. If you run this script
    five times today and BLS published nothing, the CPI tile shows the same
    number and the same delta all five times. Nothing moves because nothing
    was printed. This is the whole point.

2.  EVERY NUMBER CARRIES ITS OWN AS-OF DATE.
    Series have wildly different lags: RRP is 1 day behind, the term premium
    is ~10 days behind, Sahm is monthly, GDP is quarterly. A dashboard that
    shows them side by side without dates lies by omission. This vault has
    already been bitten by exactly that (the 2026-07-29 oil correction, where
    FRED lagged a week and the whole story had reversed inside that week).

3.  NOTHING IS FILLED IN FROM MEMORY.
    Auto-pulled data comes from FRED / CoinGecko. Everything else lives in
    macro_manual.json with an as_of and a source URL, and goes stale loudly.
    A series that fails to fetch is rendered as FAILED, never silently dropped.

4.  THE VERDICT RULES ARE WRITTEN DOWN AND PRINTED ON THE PAGE.
    So they cannot be quietly changed after seeing a result.

Usage:
    python scripts/build_macro_dashboard.py
    python scripts/build_macro_dashboard.py --verbose
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

# Paths resolve differently depending on where this runs, and deliberately from ONE
# file rather than a forked copy, so the local and cloud versions cannot drift apart.
#
#   vault layout  · the wiki checkout, snapshots live under raw/ as immutable pulls
#   flat layout   · a bare repo checkout (CI, cloud sandbox), everything beside the script
#
# Override either with the MACRO_OUT_DIR / MACRO_SNAP_DIR environment variables.
_HERE = Path(__file__).resolve().parent
_VAULT = _HERE.parent
_IS_VAULT = (_VAULT / "raw").is_dir() and (_VAULT / "index.md").is_file()

import os as _os
_out_env = _os.environ.get("MACRO_OUT_DIR")
_snap_env = _os.environ.get("MACRO_SNAP_DIR")

if _out_env:
    OUT_HTML = Path(_out_env) / "dashboard.html"
elif _IS_VAULT:
    OUT_HTML = _VAULT / "dashboard.html"
else:
    OUT_HTML = _HERE / "dashboard.html"

if _snap_env:
    SNAP_DIR = Path(_snap_env)
elif _IS_VAULT:
    SNAP_DIR = _VAULT / "raw" / "macro-data-pulls" / "snapshots"
else:
    SNAP_DIR = _HERE / "snapshots"

MANUAL = _HERE / "macro_manual.json"
REFRESH_STATUS = _HERE / "macro-refresh-status.json"

TIMEOUT = 30
UA = "Mozilla/5.0 (compatible; wiki-macro-dashboard/1.0)"
HISTORY_START = "2024-01-01"   # enough for YoY context and 20d windows


# --------------------------------------------------------------------------
# 1 · SERIES SPEC
# --------------------------------------------------------------------------
# (id, transformation)  transformation "pc1" = percent change from a year ago
FRED = [
    # policy + curve
    ("DFEDTARU", None), ("EFFR", None),
    ("DGS3MO", None), ("DGS2", None), ("DGS5", None), ("DGS10", None), ("DGS30", None),
    # real yields + inflation expectations + term premium
    ("DFII10", None), ("DFII5", None),
    ("T10YIE", None), ("T5YIE", None), ("T5YIFR", None),
    ("THREEFYTP10", None),
    # inflation
    ("CPIAUCSL", "pc1"), ("CPILFESL", "pc1"),
    ("PCEPI", "pc1"), ("PCEPILFE", "pc1"),
    # inflation COMPONENTS, so the page can show what is actually pushing CPI
    ("CPIENGSL", "pc1"),        # energy
    ("CPIUFDSL", "pc1"),        # food
    ("CUSR0000SAH1", "pc1"),    # shelter
    ("CUSR0000SASLE", "pc1"),   # services less energy services (the sticky part)
    ("CUSR0000SACL1E", "pc1"),  # core goods
    ("CPIMEDSL", "pc1"),        # medical care
    # labor
    ("UNRATE", None), ("PAYEMS", None), ("ICSA", None),
    ("CES0500000003", "pc1"), ("SAHMREALTIME", None),
    # growth
    ("A191RL1Q225SBEA", None),
    # energy
    ("DCOILBRENTEU", None), ("DCOILWTICO", None),
    # dollar
    ("DTWEXBGS", None),
    # risk appetite
    ("BAMLH0A0HYM2", None), ("VIXCLS", None),
    # liquidity
    ("WALCL", None), ("WTREGEN", None), ("RRPONTSYD", None),
    # the asset side, so the read can be scored later
    ("SP500", None), ("NASDAQCOM", None),
]


# --------------------------------------------------------------------------
# 2 · FETCH
# --------------------------------------------------------------------------
def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def fetch_fred(series_id: str, transformation: str | None = None) -> list[tuple[str, float]]:
    """Return [(iso_date, value)] oldest first. FRED's HTML pages 403 scripts;
    only this fredgraph.csv path works. One series per call, because mixing
    frequencies in one call makes FRED return a ZIP instead of a CSV."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={HISTORY_START}"
    if transformation:
        url += f"&transformation={transformation}"
    raw = _get(url)
    if raw[:2] == b"PK":
        raise RuntimeError("FRED returned a ZIP (frequency mix). Fetch one series per call.")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    if not rows:
        raise RuntimeError("empty CSV")
    out = []
    for r in rows[1:]:
        if len(r) < 2:
            continue
        d, v = r[0].strip(), r[1].strip()
        if not d or v in (".", "", "NA"):
            continue          # FRED marks missing observations with a bare dot
        try:
            out.append((d, float(v)))
        except ValueError:
            continue
    if not out:
        raise RuntimeError("no usable observations")
    return out


def _get_retry(url: str, tries: int = 4) -> bytes:
    """CoinGecko's free tier rate-limits aggressively (HTTP 429), which bites when
    the dashboard is rebuilt twice in a minute. Back off rather than lose the tile."""
    import time
    delay = 3
    for i in range(tries):
        try:
            return _get(url)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or i == tries - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def fetch_coingecko() -> dict:
    g = json.loads(_get_retry("https://api.coingecko.com/api/v3/global"))["data"]
    ids = "tether,usd-coin,bitcoin,ethereum"
    m = json.loads(_get_retry(
        f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={ids}"))
    by = {c["id"]: c for c in m}
    total = g["total_market_cap"]["usd"]
    usdt = by["tether"]["market_cap"]
    usdc = by["usd-coin"]["market_cap"]
    return {
        "total_mcap": total,
        "usdt_mcap": usdt,
        "usdc_mcap": usdc,
        "stable_total": usdt + usdc,
        "usdt_dominance": usdt / total * 100.0,
        "stable_dominance": (usdt + usdc) / total * 100.0,
        "btc_dominance": g["market_cap_percentage"]["btc"],
        "btc_price": by["bitcoin"]["current_price"],
        "btc_chg24h": by["bitcoin"]["price_change_percentage_24h"],
        "eth_price": by["ethereum"]["current_price"],
        "eth_chg24h": by["ethereum"]["price_change_percentage_24h"],
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


# --------------------------------------------------------------------------
# 3 · HISTORY HELPERS
# --------------------------------------------------------------------------
def last(series):    return series[-1] if series else None
def prev(series):    return series[-2] if series and len(series) > 1 else None


def days_ago(iso: str) -> int:
    return (date.today() - datetime.strptime(iso, "%Y-%m-%d").date()).days


def value_n_back(series, n: int):
    """Value n observations back from the latest. Used for the scoring window,
    which is deliberately longer than one print so the verdict does not
    flip-flop on a single noisy day."""
    if not series or len(series) <= n:
        return None
    return series[-1 - n][1]


def change_over(series, n: int):
    v0 = value_n_back(series, n)
    if v0 is None or not series:
        return None
    return series[-1][1] - v0


def pearson(xs, ys):
    n = len(xs)
    if n < 5:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def aligned_changes(a, b, window=20):
    """Daily changes of two series on their common dates, most recent `window`."""
    da, db = dict(a), dict(b)
    common = sorted(set(da) & set(db))
    if len(common) < window + 2:
        return [], []
    common = common[-(window + 1):]
    ca, cb = [], []
    for i in range(1, len(common)):
        ca.append(da[common[i]] - da[common[i - 1]])
        cb.append(db[common[i]] - db[common[i - 1]])
    return ca, cb


# --------------------------------------------------------------------------
# 4 · DERIVED + REGIME
# --------------------------------------------------------------------------
def derive(S: dict) -> dict:
    """S maps series_id -> list[(date, value)]. Returns computed quantities."""
    d = {}

    def L(sid):
        s = S.get(sid)
        return s[-1][1] if s else None

    def D(sid):
        s = S.get(sid)
        return s[-1][0] if s else None

    # --- curve spreads (basis points) -------------------------------------
    for name, a, b in [("2s10s", "DGS10", "DGS2"),
                       ("5s30s", "DGS30", "DGS5"),
                       ("3m10y", "DGS10", "DGS3MO")]:
        if L(a) is not None and L(b) is not None:
            d[name] = (L(a) - L(b)) * 100.0
            d[name + "_asof"] = min(x for x in (D(a), D(b)) if x)

    # 20-day change per tenor, in bps. Classifying the curve from the individual
    # legs rather than from an average is both more honest and more teachable:
    # it shows WHICH end actually moved instead of asserting a four-box label.
    for sid, key in [("DGS2", "d2_20"), ("DGS10", "d10_20"), ("DGS30", "d30_20")]:
        c = change_over(S.get(sid), 20)
        if c is not None:
            d[key] = c * 100.0

    d2, d10 = d.get("d2_20"), d.get("d10_20")
    if d2 is not None and d10 is not None:
        spread_chg = d10 - d2
        d["2s10s_chg20"] = spread_chg
        d["level_chg20"] = (d2 + d10) / 2

        # Shape comes from the spread, direction from whether BOTH legs agree.
        if abs(spread_chg) < 6:
            shape, shape_txt = "Paralel", "kedua ujung bergerak seiring, kemiringan tidak berubah"
        elif spread_chg > 0:
            shape, shape_txt = "Steepener", "spread melebar, ujung panjang relatif naik terhadap ujung pendek"
        else:
            shape, shape_txt = "Flattener", "spread menyempit, ujung pendek relatif naik terhadap ujung panjang"

        legs = (f"2 tahun {d2:+.0f} bps, 10 tahun {d10:+.0f} bps"
                + (f", 30 tahun {d['d30_20']:+.0f} bps" if d.get("d30_20") is not None else "")
                + " dalam 20 hari terakhir")

        if d2 < -5 and d10 < -5:
            label, verdict = f"Bull {shape.lower()}", "good"
            why = (f"Kedua ujung turun ({shape_txt}). Biaya uang melunak menyeluruh. "
                   f"Ini bentuk paling ramah aset beresiko, walaupun bull steepener juga bentuk "
                   f"yang biasa muncul menjelang resesi. {legs}.")
        elif d2 > 5 and d10 > 5:
            label = f"Bear {shape.lower()}"
            verdict = "bad"
            why = (f"Kedua ujung naik ({shape_txt}). "
                   + ("Ujung panjang memimpin, jadi ini cerita premi jangka dan fiskal, bukan "
                      "cerita pertumbuhan. Bentuk paling beracun untuk aset beresiko. "
                      if shape == "Steepener" else
                      "Ujung pendek memimpin, jadi pasar sedang menghargai kenaikan bunga. "
                      "Jelek terutama untuk saham growth dan crypto. ")
                   + f"{legs}.")
        elif abs(d2) < 6 and abs(d10) < 6:
            label, verdict = "Diam", "neutral"
            why = f"Kurva praktis tidak bergerak dalam 20 hari terakhir. {legs}."
        else:
            label, verdict = f"Twist {shape.lower()}", "neutral"
            why = (f"Dua ujung bergerak ke arah BERLAWANAN, jadi ini bukan bull maupun bear, "
                   f"tapi puntiran ({shape_txt}). "
                   + ("Ujung pendek turun sementara ujung panjang naik: pasar melunak soal Fed "
                      "jangka dekat tapi justru minta kompensasi lebih besar untuk risiko jangka "
                      "panjang. Campuran sinyal, jangan dipaksa jadi satu cerita. "
                      if d2 < d10 else
                      "Ujung pendek naik sementara ujung panjang turun. ")
                   + f"{legs}.")
        d["curve_shape"] = (label, why, verdict)

    # --- net liquidity ----------------------------------------------------
    # WALCL and WTREGEN are in millions, RRPONTSYD is in billions.
    w, t, r = L("WALCL"), L("WTREGEN"), L("RRPONTSYD")
    if None not in (w, t, r):
        d["net_liquidity"] = w / 1e6 - t / 1e6 - r / 1e3        # trillions USD
        d["net_liquidity_asof"] = min(x for x in (D("WALCL"), D("WTREGEN"), D("RRPONTSYD")) if x)
        # same computation one weekly print back, so we can show a direction
        try:
            w2 = S["WALCL"][-2][1] / 1e6
            t2 = S["WTREGEN"][-2][1] / 1e6
            r2 = S["RRPONTSYD"][-2][1] / 1e3
            d["net_liquidity_chg"] = d["net_liquidity"] - (w2 - t2 - r2)
        except (KeyError, IndexError):
            pass

    # --- stock/bond correlation: THE regime detector ----------------------
    if S.get("SP500") and S.get("DGS10"):
        ca, cb = aligned_changes(S["SP500"], S["DGS10"], window=20)
        d["stock_bond_corr"] = pearson(ca, cb)

    # --- Sahm gap ---------------------------------------------------------
    sahm = L("SAHMREALTIME")
    if sahm is not None:
        d["sahm"] = sahm
        d["sahm_gap"] = 0.50 - sahm

    # --- payroll monthly change ------------------------------------------
    p = S.get("PAYEMS")
    if p and len(p) > 1:
        d["payems_chg"] = p[-1][1] - p[-2][1]          # thousands of jobs
        d["payems_asof"] = p[-1][0]

    # --- real policy rate against the Fed's own target measure -----------
    if L("DFEDTARU") is not None and L("PCEPILFE") is not None:
        d["real_policy_rate"] = L("DFEDTARU") - L("PCEPILFE")

    # --- core CPI vs core PCE gap, the vault's open tension ---------------
    if L("CPILFESL") is not None and L("PCEPILFE") is not None:
        d["core_gap"] = L("PCEPILFE") - L("CPILFESL")

    return d


def regime(S, d) -> dict:
    """Runs BEFORE any metric is scored, because several metrics flip sign
    depending on the answer."""
    corr = d.get("stock_bond_corr")
    if corr is None:
        driver, driver_note = "unknown", "Korelasi saham-obligasi gagal dihitung."
    elif corr > 0.20:
        driver = "growth"
        driver_note = ("Saham dan yield bergerak SEARAH. Pasar sedang dikendarai cerita "
                       "pertumbuhan: yield naik dibaca sebagai ekonomi kuat, dan saham ikut naik.")
    elif corr < -0.20:
        driver = "rates"
        driver_note = ("Saham dan yield bergerak BERLAWANAN. Pasar sedang dikendarai discount "
                       "rate: tiap kenaikan yield langsung menekan aset beresiko. Ini rezim inflasi.")
    else:
        driver = "mixed"
        driver_note = ("Korelasi saham-obligasi lemah. Tidak ada satu penggerak yang dominan "
                       "saat ini, jadi jangan paksakan satu cerita.")

    sahm = d.get("sahm")
    if sahm is None:
        labor, labor_note = "unknown", "Sahm Rule tidak tersedia."
    elif sahm < 0.50:
        labor = "inflation"
        labor_note = (f"Sahm Rule di {sahm:+.2f}, masih jauh di bawah ambang resesi 0,50. "
                      "Artinya kita di rezim GOOD NEWS IS BAD NEWS: data tenaga kerja yang kuat "
                      "berarti Fed tidak perlu melunak, dan itu jelek untuk aset beresiko. "
                      "Data tenaga kerja yang lemah justru dibaca positif.")
    else:
        labor = "recession"
        labor_note = (f"Sahm Rule di {sahm:+.2f}, sudah menembus ambang 0,50. Rezim berubah jadi "
                      "BAD NEWS IS BAD NEWS: data lemah bukan lagi harapan pemotongan bunga, "
                      "tapi tanda laba perusahaan akan hancur.")

    oas = None
    s = S.get("BAMLH0A0HYM2")
    if s:
        oas = s[-1][1]
        oas_chg = change_over(s, 20)
        if oas < 3.5 and (oas_chg or 0) <= 0.10:
            credit, credit_note = "calm", ("Spread kredit high-yield sempit dan tidak melebar. "
                                           "Selera risiko masih hidup. Ini pengukur paling jujur "
                                           "yang ada, lebih dari indeks saham itu sendiri.")
        elif oas < 4.5:
            credit, credit_note = "watch", "Spread kredit mulai bergerak. Layak diawasi."
        else:
            credit, credit_note = "stress", "Spread kredit melebar. Pasar kredit sedang takut."
    else:
        credit, credit_note = "unknown", "Spread HY tidak tersedia."

    return {"driver": driver, "driver_note": driver_note, "corr": corr,
            "labor": labor, "labor_note": labor_note,
            "credit": credit, "credit_note": credit_note, "oas": oas}


# --------------------------------------------------------------------------
# 5 · SCORING RULES  (printed on the page verbatim, see RULES_TEXT)
# --------------------------------------------------------------------------
def score_dir(chg, good_when_falling=True, dead=0.0):
    """Generic: which direction is friendly to risk assets."""
    if chg is None:
        return "neutral"
    if abs(chg) <= dead:
        return "neutral"
    falling = chg < 0
    return "good" if falling == good_when_falling else "bad"


RULES_TEXT = [
    ("Yield riil 10 tahun (DFII10)", "Turun = BAGUS. Ini biaya uang yang sesungguhnya. "
     "Kalau cuma boleh pantau satu angka untuk crypto dan emas, pantau ini. Ambang mati 10 bps / 20 hari."),
    ("Term premium 10 tahun", "Naik = JELEK. Ini bagian yield yang bukan soal Fed, tapi soal "
     "risiko memegang utang jangka panjang: defisit, banjir penerbitan, kredibilitas fiskal. "
     "Kenaikan yield lewat jalur ini yang paling beracun."),
    ("Spread kredit high-yield", "Melebar = JELEK. Kalau ini bertentangan dengan indeks saham, "
     "percayai kredit."),
    ("Core CPI / Core PCE", "Naik = JELEK. Yang direaksi Fed itu core, bukan headline, karena "
     "suku bunga tidak bisa memproduksi minyak."),
    ("Pengangguran & klaim", "TERGANTUNG REZIM. Sahm di bawah 0,50: data lemah = BAGUS "
     "(Fed melunak). Sahm di atas 0,50: data lemah = JELEK (resesi datang)."),
    ("GDP", "TERGANTUNG REZIM. Rezim pertumbuhan: tinggi = bagus. Rezim inflasi: tinggi = jelek, "
     "karena Fed jadi punya alasan untuk tetap galak."),
    ("Minyak (WTI/Brent)", "Naik = JELEK. Guncangan pasokan itu stagflasioner: inflasi naik DAN "
     "pertumbuhan turun, jadi obligasi dan saham kena bareng."),
    ("Dolar", "Naik = JELEK. Dolar kuat mengetatkan kondisi keuangan global."),
    ("Net liquidity (WALCL − TGA − RRP)", "Naik = BAGUS. Ini jumlah uang di sistem, bukan harganya."),
    ("USDT dominance", "Naik = JELEK. Uang parkir di stablecoin artinya orang keluar dari risiko "
     "tanpa keluar dari crypto."),
    ("Peluang hike Fed", "Naik = JELEK."),
]


# --------------------------------------------------------------------------
# 6 · RENDER
# --------------------------------------------------------------------------
def spark(series, n=60, good_when_falling=True, w=104, h=26):
    """Inline SVG sparkline. No library, no external request. Gives a beginner the
    shape of the last few months at a glance, which a single number cannot."""
    if not series or len(series) < 4:
        return ""
    pts = [v for _, v in series[-n:]]
    lo, hi = min(pts), max(pts)
    rng = (hi - lo) or 1.0
    step = w / max(len(pts) - 1, 1)
    coords = [(i * step, h - 2 - ((v - lo) / rng) * (h - 4)) for i, v in enumerate(pts)]
    d = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    rising = pts[-1] >= pts[0]
    good = (not rising) == good_when_falling
    col = "var(--good)" if good else "var(--bad)"
    lx, ly = coords[-1]
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'preserveAspectRatio="none" aria-hidden="true">'
            f'<polyline points="{d}" fill="none" stroke="{col}" stroke-width="1.6" '
            f'stroke-linejoin="round" stroke-linecap="round" opacity=".85"/>'
            f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="2.1" fill="{col}"/></svg>')


def _id_prose(html):
    """Convert decimal points to commas inside prose. Safe here because conclusion
    bodies contain no CSS, no URLs and no version strings."""
    import re as _re
    return _re.sub(r"(?<=\d)\.(?=\d)", ",", html)


def concl(body_html, verdict="neutral", title="Kesimpulan bagian ini"):
    body_html = _id_prose(body_html)
    """Every section ends with one of these. A wall of numbers with no reading is
    what made the first version unfriendly to a beginner."""
    return (f'<div class="concl {verdict}"><div class="ct">{esc(title)}</div>'
            f'<div class="cb">{body_html}</div></div>')


def arah(x, naik="naik", turun="turun", datar="praktis datar", dead=0.0):
    if x is None:
        return "tidak diketahui"
    if abs(x) <= dead:
        return datar
    return naik if x > 0 else turun


def monthly_avg(series, y, m):
    """Average of a daily series over one calendar month. CPI eats the monthly
    average, never the spot spike, so this is the right unit for the oil channel."""
    vals = [v for dt, v in series if dt[:7] == f"{y:04d}-{m:02d}"]
    return sum(vals) / len(vals) if vals else None


# --------------------------------------------------------------------------
# 5b · SECTION ANALYSIS  (live prose, generated from the numbers above)
# --------------------------------------------------------------------------
def analyse_bonds(S, d, R):
    """Answers, in words, the question the page poses: are stocks and yields moving
    together or opposite, and therefore what KIND of yield move is this."""
    corr = R.get("corr")
    out = []

    if corr is None:
        out.append("<p>Korelasi saham-obligasi gagal dihitung, jadi pertanyaan searah/berlawanan "
                   "tidak bisa dijawab pada run ini.</p>")
    else:
        if corr < -0.20:
            jawab = ("<strong>BERLAWANAN.</strong> Jadi jawabannya: pasar sedang dikendarai "
                     "<strong>discount rate</strong>, bukan pertumbuhan. Tiap kenaikan yield "
                     "langsung menekan saham dan crypto. Ini rezim inflasi, dan di rezim ini "
                     "tidak ada versi 'yield naik yang bagus'.")
        elif corr > 0.20:
            jawab = ("<strong>SEARAH.</strong> Jadi jawabannya: pasar sedang dikendarai "
                     "<strong>pertumbuhan</strong>. Yield naik dibaca sebagai ekonomi kuat, dan "
                     "saham bisa ikut naik. Ini rezim <em>good news is good news</em>.")
        else:
            jawab = ("<strong>TIDAK JELAS.</strong> Korelasinya terlalu lemah untuk menyebut satu "
                     "penggerak dominan. Jangan paksakan satu cerita.")
        out.append(f"<p><strong>Saham dan yield sekarang bergerak {jawab}</strong> "
                   f"Angkanya: korelasi {corr:+.2f} antara perubahan harian S&amp;P 500 dan "
                   f"perubahan harian yield 10 tahun, diukur pada 20 hari terakhir. "
                   f"Skalanya -1 sampai +1: di bawah -0,20 disebut berlawanan, di atas +0,20 "
                   f"disebut searah.</p>")

    d2, d10, d30 = d.get("d2_20"), d.get("d10_20"), d.get("d30_20")
    tp = S.get("THREEFYTP10")
    tp_chg = change_over(tp, 20) if tp else None

    if None not in (d2, d10):
        if d2 < -3 and d10 > 3:
            diag = ("Ujung pendek <strong>turun</strong> sementara ujung panjang "
                    "<strong>naik</strong>. Artinya pasar sebenarnya sedang melunak soal Fed "
                    "jangka dekat, tapi justru minta bayaran lebih mahal untuk memegang utang "
                    "jangka panjang. Kenaikan yield yang terjadi sekarang datang dari sisi "
                    "<strong>harga risiko</strong>, bukan dari jalur suku bunga.")
            v = "bad"
        elif d10 > 3 and d2 > 3:
            diag = ("Kedua ujung naik bersama, jadi ini kenaikan yield menyeluruh. Kalau ujung "
                    "pendek yang memimpin, itu Fed. Kalau ujung panjang yang memimpin, itu fiskal.")
            v = "bad"
        elif d10 < -3 and d2 < -3:
            diag = ("Kedua ujung turun. Biaya uang melunak menyeluruh, dan ini bentuk paling "
                    "ramah untuk aset beresiko.")
            v = "good"
        else:
            diag = "Kurva belum bergerak cukup jauh untuk memberi sinyal yang jelas."
            v = "neutral"
        out.append(f"<p><strong>Jenis pergerakannya.</strong> Dalam 20 hari terakhir: 2 tahun "
                   f"{d2:+.0f} bps, 10 tahun {d10:+.0f} bps"
                   + (f", 30 tahun {d30:+.0f} bps" if d30 is not None else "") + ". " + diag + "</p>")
    else:
        v = "neutral"

    if tp_chg is not None and tp:
        out.append(f"<p><strong>Konfirmasi dari term premium.</strong> Term premium 10 tahun ada "
                   f"di {tp[-1][1]:.2f}% dan {arah(tp_chg, 'naik', 'turun', 'datar', 0.03)} "
                   f"{abs(tp_chg):.2f} poin dalam 20 hari. "
                   + ("Naiknya term premium memastikan bahwa sebagian kenaikan yield itu murni "
                      "kompensasi risiko: defisit, banjir penerbitan utang, kredibilitas fiskal. "
                      "Inilah bagian yang tidak bisa disembuhkan oleh Fed, dan yang paling "
                      "beracun untuk aset beresiko."
                      if tp_chg > 0.03 else
                      "Term premium yang tidak naik berarti kenaikan yield (kalau ada) lebih "
                      "banyak soal jalur suku bunga daripada soal ketakutan fiskal.")
                   + "</p>")

    if R.get("credit") == "calm":
        out.append("<p><strong>Tapi ada penyeimbangnya.</strong> Spread kredit high-yield masih "
                   "sempit, artinya pasar kredit belum ikut takut. Selama itu bertahan, tekanan "
                   "dari sisi obligasi belum berubah jadi krisis. Kalau spread ini mulai melebar "
                   "bersamaan dengan yield panjang yang naik, barulah situasinya berubah serius.</p>")
    return "".join(out), v


def analyse_inflation(S, d):
    out, comps = [], []
    for sid, lbl in [("CPIENGSL", "Energi"), ("CPIUFDSL", "Pangan"),
                     ("CUSR0000SAH1", "Sewa/tempat tinggal"),
                     ("CUSR0000SASLE", "Jasa (di luar energi)"),
                     ("CUSR0000SACL1E", "Barang inti"), ("CPIMEDSL", "Kesehatan")]:
        s = S.get(sid)
        if s:
            comps.append((lbl, s[-1][1], change_over(s, 3)))

    head, core = S.get("CPIAUCSL"), S.get("CPILFESL")
    eng = S.get("CPIENGSL")
    v = "neutral"

    if head and core:
        gap = head[-1][1] - core[-1][1]
        out.append(f"<p><strong>Kenapa headline dan core berbeda.</strong> Headline CPI "
                   f"{head[-1][1]:.2f}%, core {core[-1][1]:.2f}%, selisih {gap:+.2f} poin. "
                   + (f"Selisih itu hampir seluruhnya energi, yang sedang berjalan "
                      f"{eng[-1][1]:+.1f}% dibanding setahun lalu. "
                      if eng else "")
                   + "Ini pola khas guncangan pasokan energi yang <strong>belum</strong> merembes "
                     "ke harga-harga lain. Dan itu penting, karena Fed bereaksi ke core, bukan "
                     "headline: suku bunga tidak bisa memproduksi minyak."
                   if gap > 0.3 else
                   "Headline dan core berdekatan, artinya inflasi yang ada sekarang bersifat "
                   "menyeluruh, bukan sekadar guncangan energi. Kondisi seperti ini justru "
                   "lebih memaksa Fed untuk bertindak.")
        out[-1] += "</p>"

    goods = S.get("CUSR0000SACL1E")
    svc = S.get("CUSR0000SASLE")
    if goods and svc:
        out.append(f"<p><strong>Di dalam core, dua mesinnya berlawanan.</strong> Barang inti cuma "
                   f"{goods[-1][1]:+.2f}% sementara jasa {svc[-1][1]:+.2f}%. "
                   f"Barang sudah selesai berinflasi; yang menahan core tetap tinggi adalah jasa "
                   f"dan sewa, dan dua komponen itu bergerak lambat. Artinya core tidak akan turun "
                   f"cepat walaupun minyak jatuh besok. Kalau kamu mau menebak arah core, "
                   f"perhatikan upah, bukan komoditas.</p>")

    # forward-looking energy base effect, computed rather than asserted
    brent = S.get("DCOILBRENTEU")
    proj = None
    if brent:
        today = datetime.strptime(brent[-1][0], "%Y-%m-%d").date()
        cur = monthly_avg(brent, today.year, today.month)
        cur_ly = monthly_avg(brent, today.year - 1, today.month)
        pm = today.month - 1 or 12
        py = today.year if today.month > 1 else today.year - 1
        prev = monthly_avg(brent, py, pm)
        prev_ly = monthly_avg(brent, py - 1, pm)
        if None not in (cur, cur_ly, prev, prev_ly):
            yoy_now = (cur / cur_ly - 1) * 100
            yoy_prev = (prev / prev_ly - 1) * 100
            proj = yoy_now - yoy_prev
            out.append(
                f"<p><strong>Perkiraan arah cetakan berikutnya (analisa sendiri, bukan dari "
                f"FedWatch).</strong> Yang masuk CPI itu rata-rata bulanan dibanding bulan yang "
                f"sama tahun lalu, bukan harga spot. Brent rata-rata {cur:.1f} bulan ini melawan "
                f"{cur_ly:.1f} setahun lalu, jadi basis tahunannya {yoy_now:+.1f}%. Bulan "
                f"sebelumnya {yoy_prev:+.1f}%. "
                + (f"Karena angka ini <strong>naik</strong> {proj:+.1f} poin, kontribusi energi ke "
                   f"headline CPI sedang <strong>berakselerasi</strong>, jadi tekanan ke headline "
                   f"cetakan berikutnya condong ke atas."
                   if proj > 1 else
                   f"Karena angka ini <strong>turun</strong> {proj:+.1f} poin, kontribusi energi ke "
                   f"headline CPI sedang <strong>melambat</strong>, jadi headline cetakan berikutnya "
                   f"condong melunak walaupun harga minyak terlihat tinggi."
                   if proj < -1 else
                   "Angka ini praktis tidak berubah, jadi energi kemungkinan tidak menambah maupun "
                   "mengurangi tekanan berarti di cetakan berikutnya.")
                + " Catatan jujur: data minyak FRED tertinggal sekitar seminggu, dan bulan berjalan "
                  "belum lengkap, jadi ini estimasi arah, bukan ramalan angka.</p>")
            v = "bad" if proj > 1 else "good" if proj < -1 else "neutral"

    if d.get("core_gap") is not None:
        out.append(f"<p><strong>Yang belum selesai.</strong> Core PCE dan core CPI berselisih "
                   f"{d['core_gap']:+.2f} poin. Keduanya mengaku mengukur hal yang sama. Yang "
                   f"dipakai Fed adalah PCE. Selama gap ini belum tertutup, membaca CPI saja "
                   f"bikin Fed terlihat hampir menang padahal ukurannya sendiri bilang sebaliknya.</p>")
    return "".join(out), v, comps


def analyse_labor(S, d, R):
    out = []
    u, ic, pc = S.get("UNRATE"), S.get("ICSA"), d.get("payems_chg")
    sahm = d.get("sahm")

    if sahm is not None:
        out.append(f"<p><strong>Rezimnya dulu, baru datanya.</strong> Sahm Rule {sahm:+.2f} "
                   f"melawan ambang resesi 0,50, jadi jaraknya masih {0.50 - sahm:.2f} poin. "
                   + ("Selama di bawah ambang, data tenaga kerja yang <strong>lemah</strong> "
                      "dibaca pasar sebagai kabar <strong>baik</strong>, karena artinya Fed punya "
                      "alasan melunak. Ini yang bikin pemula bingung: berita PHK bisa bikin saham "
                      "naik. Bukan karena pasar kejam, tapi karena yang dihargai adalah suku bunga."
                      if sahm < 0.50 else
                      "Ambang sudah tertembus, jadi artinya berbalik: data lemah bukan lagi harapan "
                      "pemotongan bunga, tapi tanda laba perusahaan akan hancur.") + "</p>")

    bits = []
    if pc is not None:
        bits.append(f"payroll {'bertambah' if pc > 0 else 'BERKURANG'} {abs(pc):,.0f} ribu")
    if u:
        bits.append(f"pengangguran {u[-1][1]:.1f}%")
    if ic:
        bits.append(f"klaim awal {ic[-1][1]:,.0f}")
    if bits:
        lemah = (pc is not None and pc < 75)
        out.append(f"<p><strong>Datanya sekarang:</strong> " + ", ".join(bits) + ". "
                   + (("Payroll yang <strong>negatif</strong> itu kejadian besar, bukan detail. "
                       if pc is not None and pc < 0 else "")
                      + ("Kombinasi ini condong <strong>lemah</strong>, dan di rezim sekarang itu "
                         "justru <strong>ramah</strong> untuk aset beresiko."
                         if lemah and (sahm or 0) < 0.50 else
                         "Kombinasi ini condong <strong>kuat</strong>, dan di rezim sekarang itu "
                         "berarti Fed tidak terdesak melunak, jadi <strong>menekan</strong> aset beresiko."))
                   + "</p>")
    out.append("<p><strong>Kalau mau tahu duluan:</strong> klaim awal keluar tiap Kamis dan itu "
               "data ketenagakerjaan tercepat yang ada. NFP baru Jumat pertama tiap bulan, "
               "pengangguran ikut di situ, dan JOLTS paling lambat. ADP diabaikan saja, "
               "korelasinya ke NFP payah.</p>")
    v = "good" if (sahm is not None and sahm < 0.50 and (pc or 0) < 75) else "neutral"
    return "".join(out), v


def analyse_liquidity(S, d, cg):
    out = []
    nl, nlc = d.get("net_liquidity"), d.get("net_liquidity_chg")
    rrp, walcl, tga = S.get("RRPONTSYD"), S.get("WALCL"), S.get("WTREGEN")

    out.append("<p><strong>Cara bacanya sederhana.</strong> Bayangkan sistem keuangan sebagai "
               "kolam. Neraca Fed itu keran yang mengisi. TGA (rekening kas pemerintah) dan RRP "
               "(parkiran semalam) itu dua ember yang menahan air keluar dari kolam. Net liquidity "
               "adalah air yang benar-benar tersisa di kolam untuk dibelanjakan ke aset.</p>")

    if nl is not None:
        out.append(f"<p><strong>Sekarang kolamnya berisi ${nl:.3f} triliun</strong>"
                   + (f", dan {arah(nlc, 'naik', 'turun', 'praktis datar', 0.002)} "
                      f"${abs(nlc)*1000:.0f} miliar dari cetakan mingguan sebelumnya. " if nlc is not None else ". ")
                   + ("Arah turun berarti bahan bakar sedang berkurang, walaupun perubahan satu "
                      "minggu itu kecil dan jangan dibaca berlebihan."
                      if (nlc or 0) < 0 else
                      "Arah naik berarti bahan bakar sedang bertambah.") + "</p>")

    if rrp and rrp[-1][1] < 5:
        out.append(f"<p><strong>Dan ini bagian yang paling penting di bagian ini.</strong> Ember "
                   f"RRP tinggal ${rrp[-1][1]:.2f} miliar, praktis kosong. Sepanjang 2023-2024, "
                   f"pengurasan ember inilah yang jadi bahan bakar besar buat aset beresiko: uang "
                   f"pindah dari parkiran Fed ke pasar. <strong>Sumber itu sudah habis.</strong> "
                   f"Ke depan, tambahan likuiditas harus datang dari Fed melonggarkan neraca atau "
                   f"dari TGA yang dikuras. Ini hal kecil yang jarang masuk berita tapi mengubah "
                   f"dari mana kenaikan berikutnya bisa dibiayai.</p>")

    if cg:
        out.append(f"<p><strong>Khusus crypto</strong>, ada kolam kedua: pasokan stablecoin "
                   f"${cg['stable_total']/1e9:,.0f} miliar. Ini uang yang sudah ada di dalam "
                   f"ekosistem dan tinggal dibelanjakan. USDT dominance {cg['usdt_dominance']:.2f}% "
                   f"memberi tahu seberapa banyak dari uang itu yang masih duduk diam. Turun = "
                   f"uangnya sedang dipakai beli aset. Naik = orang kabur ke tempat aman tanpa "
                   f"keluar dari crypto.</p>")

    v = "bad" if (nlc is not None and nlc < -0.002) else "good" if (nlc or 0) > 0.002 else "neutral"
    return "".join(out), v


def analyse_overall(S, d, R, cg):
    """The one-paragraph read a beginner should be able to stop at."""
    good, bad = [], []
    ry = change_over(S.get("DFII10"), 20)
    if ry is not None:
        (bad if ry > 0 else good).append(
            f"yield riil {'naik' if ry > 0 else 'turun'} {abs(ry)*100:.0f} bps sebulan")
    tp = change_over(S.get("THREEFYTP10"), 20)
    if tp is not None and abs(tp) > 0.03:
        (bad if tp > 0 else good).append(
            f"term premium {'naik' if tp > 0 else 'turun'}")
    oas = change_over(S.get("BAMLH0A0HYM2"), 20)
    if oas is not None:
        (bad if oas > 0.05 else good).append(
            "spread kredit " + ("melebar" if oas > 0.05 else "sempit dan stabil"))
    dxy = change_over(S.get("DTWEXBGS"), 20)
    if dxy is not None:
        (bad if dxy > 0 else good).append(f"dolar {'menguat' if dxy > 0 else 'melemah'}")
    oil = change_over(S.get("DCOILBRENTEU"), 20)
    if oil is not None:
        (bad if oil > 0 else good).append(f"minyak {'naik' if oil > 0 else 'turun'}")
    nlc = d.get("net_liquidity_chg")
    if nlc is not None:
        (bad if nlc < 0 else good).append(f"net liquidity {'turun' if nlc < 0 else 'naik'}")

    out = [f"<p><strong>Yang menekan:</strong> " + (", ".join(bad) if bad else "tidak ada") + ".<br>"
           f"<strong>Yang mendukung:</strong> " + (", ".join(good) if good else "tidak ada") + ".</p>"]

    if R.get("driver") == "rates":
        out.append("<p>Karena pasar sedang dikendarai <strong>discount rate</strong>, bobot "
                   "terbesar ada di baris yield riil dan term premium. Kabar ekonomi yang bagus "
                   "tidak akan menolong selama dua angka itu naik, dan itulah sebabnya berita "
                   "positif kadang tetap diikuti pasar turun.</p>")
    elif R.get("driver") == "growth":
        out.append("<p>Karena pasar sedang dikendarai <strong>pertumbuhan</strong>, kabar ekonomi "
                   "yang kuat justru dibaca positif, dan kenaikan yield tidak otomatis jelek.</p>")

    net = len(good) - len(bad)
    v = "good" if net >= 2 else "bad" if net <= -2 else "neutral"
    out.append("<p><strong>Bacaan keseluruhan:</strong> "
               + ("condong ramah untuk aset beresiko, tapi tetap cek bagian 03 dan 06 sebelum "
                  "menyimpulkan." if v == "good" else
                  "condong menekan aset beresiko. Bukan berarti harga harus turun besok, tapi "
                  "arah anginnya sedang melawan." if v == "bad" else
                  "campuran, tidak ada arah dominan. Di kondisi begini, pergerakan besar biasanya "
                  "datang dari posisi pasar yang terlalu satu sisi, bukan dari makro. Lihat "
                  "bagian 07.") + "</p>")
    return "".join(out), v


CSS = """
:root{
  --bg:#f6f6f3; --card:#fff; --ink:#17171a; --muted:#6a6a72; --line:#e4e4de;
  --good:#1a7f4b; --good-bg:#e8f5ed; --bad:#c02626; --bad-bg:#fdecec;
  --warn:#9a6200; --warn-bg:#fdf3e0; --neutral:#5d5d66; --neutral-bg:#f0f0ee;
  --accent:#b4530a;
}
:root:not([data-theme="light"]){}
@media (prefers-color-scheme:dark){
  :root{
    --bg:#131315; --card:#1c1c1f; --ink:#ececf0; --muted:#9b9ba4; --line:#2d2d32;
    --good:#5fd398; --good-bg:#12291f; --bad:#ff7b7b; --bad-bg:#2c1618;
    --warn:#f0b95c; --warn-bg:#2b2113; --neutral:#a0a0aa; --neutral-bg:#232327;
    --accent:#e8834a;
  }
}
*{box-sizing:border-box}
body{margin:0;padding:0 0 5rem;background:var(--bg);color:var(--ink);
  font:16px/1.65 ui-sans-serif,-apple-system,"Segoe UI",system-ui,sans-serif;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:1140px;margin:0 auto;padding:0 1.1rem}

/* masthead */
.top{background:linear-gradient(180deg,var(--card),transparent);
  border-bottom:1px solid var(--line);padding:2.2rem 0 1.4rem;margin-bottom:0}
h1{font-size:2rem;margin:0 0 .3rem;letter-spacing:-.03em;font-weight:700}
.sub{color:var(--muted);font-size:.86rem;margin:0}

/* sticky nav */
nav{position:sticky;top:0;z-index:20;background:var(--bg);
  border-bottom:1px solid var(--line);margin-bottom:2rem;
  backdrop-filter:saturate(1.4) blur(8px)}
nav .navin{max-width:1140px;margin:0 auto;padding:.55rem 1.1rem;
  display:flex;gap:.15rem;overflow-x:auto;-webkit-overflow-scrolling:touch;
  scrollbar-width:none}
nav .navin::-webkit-scrollbar{display:none}
nav a{color:var(--muted);text-decoration:none;font-size:.79rem;font-weight:600;
  padding:.35rem .6rem;border-radius:7px;white-space:nowrap}
nav a:hover{color:var(--ink);background:var(--neutral-bg)}

h2{font-size:1.22rem;margin:3.2rem 0 .3rem;letter-spacing:-.02em;scroll-margin-top:3.6rem;
  font-weight:680}
h2 .n{color:var(--accent);font-variant-numeric:tabular-nums;margin-right:.55rem;
  font-size:.82rem;font-weight:700;vertical-align:.18em;letter-spacing:.06em}
.h2sub{color:var(--muted);font-size:.87rem;margin:0 0 1.1rem;max-width:74ch}

/* section conclusion */
.concl{border-radius:12px;padding:1rem 1.15rem;margin:1.3rem 0 .5rem;
  border:1px solid var(--line);border-left-width:5px;background:var(--card)}
.concl.good{border-left-color:var(--good);background:var(--good-bg)}
.concl.bad{border-left-color:var(--bad);background:var(--bad-bg)}
.concl.neutral{border-left-color:var(--muted)}
.concl .ct{font-size:.7rem;text-transform:uppercase;letter-spacing:.1em;
  font-weight:800;color:var(--muted);margin-bottom:.5rem}
.concl .cb{font-size:.91rem}
.concl .cb p{margin:.5rem 0}
.concl .cb p:first-child{margin-top:0}
.concl .cb p:last-child{margin-bottom:0}

h3.h3{font-size:1rem;margin:1.8rem 0 .3rem;font-weight:660;letter-spacing:-.01em}

/* sparkline */
.spark{display:block;margin:.45rem 0 .1rem;width:100%;height:26px}

/* verdict banner */
.banner{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:1.4rem 1.5rem;margin-bottom:1.5rem}
.banner .big{font-size:1.3rem;font-weight:650;letter-spacing:-.02em;margin:0 0 .6rem}
.banner p{margin:.5rem 0;font-size:.94rem}
.pillrow{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:1rem}
.pill{font-size:.78rem;padding:.3rem .7rem;border-radius:999px;font-weight:600;
  border:1px solid transparent}
.pill.good{background:var(--good-bg);color:var(--good);border-color:var(--good)}
.pill.bad{background:var(--bad-bg);color:var(--bad);border-color:var(--bad)}
.pill.warn{background:var(--warn-bg);color:var(--warn);border-color:var(--warn)}
.pill.neutral{background:var(--neutral-bg);color:var(--neutral);border-color:var(--line)}

/* tiles */
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(232px,1fr));gap:.8rem}
.tile{background:var(--card);border:1px solid var(--line);border-left-width:4px;
  border-radius:11px;padding:.85rem .95rem}
.tile.good{border-left-color:var(--good)} .tile.bad{border-left-color:var(--bad)}
.tile.neutral{border-left-color:var(--line)} .tile.fail{border-left-color:var(--warn)}
.tile .lbl{font-size:.76rem;color:var(--muted);font-weight:600;text-transform:uppercase;
  letter-spacing:.05em;margin-bottom:.25rem;display:block}
.tile .val{font-size:1.5rem;font-weight:640;letter-spacing:-.03em;
  font-variant-numeric:tabular-nums;line-height:1.15}
.tile .chg{font-size:.84rem;font-weight:600;margin-top:.15rem;font-variant-numeric:tabular-nums}
.tile .chg.up{color:var(--bad)} .tile .chg.dn{color:var(--good)}
.tile .chg.flat{color:var(--muted)}
.tile .chg.upg{color:var(--good)} .tile .chg.dnb{color:var(--bad)}
.tile .w20{font-size:.76rem;color:var(--muted);margin-top:.3rem;
  font-variant-numeric:tabular-nums}
.tile .tag{font-size:.68rem;font-weight:700;padding:.05rem .35rem;border-radius:4px;
  margin-left:.15rem;text-transform:uppercase;letter-spacing:.04em}
.tag.good{background:var(--good-bg);color:var(--good)}
.tag.bad{background:var(--bad-bg);color:var(--bad)}
.tag.neutral{background:var(--neutral-bg);color:var(--neutral)}
.legend{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:.7rem .95rem;font-size:.83rem;color:var(--muted);margin-bottom:1rem}
.legend b{color:var(--ink)}
.tile .asof{font-size:.72rem;color:var(--muted);margin-top:.45rem;
  border-top:1px dashed var(--line);padding-top:.4rem}
.tile .means{font-size:.8rem;color:var(--muted);margin-top:.5rem;line-height:1.45}
.stale{color:var(--warn);font-weight:600}

/* details / explainer */
details{background:var(--card);border:1px solid var(--line);border-radius:11px;
  margin:.6rem 0;overflow:hidden}
summary{cursor:pointer;padding:.8rem 1rem;font-weight:600;font-size:.92rem;
  list-style:none;display:flex;justify-content:space-between;gap:1rem;align-items:center}
summary::-webkit-details-marker{display:none}
summary::after{content:"+";color:var(--muted);font-weight:400;font-size:1.2rem}
details[open] summary::after{content:"−"}
details[open] summary{border-bottom:1px solid var(--line)}
.dbody{padding:.9rem 1rem 1.1rem;font-size:.9rem}
.dbody p{margin:.55rem 0}
.dbody ul{margin:.5rem 0;padding-left:1.15rem}
.dbody li{margin:.3rem 0}

/* tables */
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:.86rem;min-width:460px}
th,td{text-align:left;padding:.5rem .6rem;border-bottom:1px solid var(--line);
  vertical-align:top}
th{font-size:.74rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}

/* calendar */
.cal{display:flex;flex-direction:column;gap:.5rem}
.ev{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:.75rem .9rem;display:grid;grid-template-columns:auto 1fr;gap:.9rem}
.ev .when{font-variant-numeric:tabular-nums;font-weight:640;font-size:.85rem;
  white-space:nowrap;min-width:5.4rem}
.ev .when small{display:block;font-weight:400;color:var(--muted);font-size:.74rem}
.ev.high{border-left:4px solid var(--accent)}
.ev .t{font-weight:640;font-size:.92rem}
.ev .w{font-size:.84rem;color:var(--muted);margin-top:.25rem;line-height:1.5}
.ev .cd{font-size:.72rem;color:var(--accent);font-weight:600}

.note{background:var(--warn-bg);border:1px solid var(--warn);border-radius:10px;
  padding:.85rem 1rem;font-size:.86rem;margin:1rem 0;color:var(--ink)}
.foot{margin-top:3.5rem;padding-top:1.2rem;border-top:1px solid var(--line);
  color:var(--muted);font-size:.8rem}
a{color:var(--accent)}
code{background:var(--neutral-bg);padding:.1rem .35rem;border-radius:4px;font-size:.85em}
"""


def idnum(text):
    """Swap English number punctuation for Indonesian: 1,234.56 becomes 1.234,56.
    Applied only to formatted numbers and to prose blocks, never to CSS or markup,
    because a blanket swap over the whole document would corrupt stroke-width:1.6
    and friends."""
    return text.translate(str.maketrans({",": ".", ".": ","}))


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def fmt(v, dec=2, suffix=""):
    if v is None:
        return "—"
    return idnum(f"{v:,.{dec}f}") + suffix


def tile(label, value, chg_html, asof_html, means, verdict, trend_html="", spark_html=""):
    return f"""<div class="tile {verdict}">
<span class="lbl">{esc(label)}</span>
<div class="val">{value}</div>
{chg_html}
{spark_html}
{trend_html}
<div class="asof">{asof_html}</div>
<div class="means">{means}</div>
</div>"""


def trend_block(chg20, dec=2, suffix="", good_when_falling=True):
    """The 20-observation window that drives the tile's colour. Shown explicitly so
    a green border sitting next to a red arrow reads as two time windows rather
    than as a contradiction."""
    if chg20 is None:
        return ""
    if abs(chg20) < 1e-9:
        return ('<div class="w20">tren 20 hari: datar '
                '<span class="tag neutral">netral</span></div>')
    good = (chg20 < 0) == good_when_falling
    arrow = "▲" if chg20 > 0 else "▼"
    tag = ("ramah" if good else "menekan")
    return (f'<div class="w20">tren 20 hari: {arrow} {idnum(f"{chg20:+,.{dec}f}")}{suffix} '
            f'<span class="tag {"good" if good else "bad"}">{tag}</span></div>')


def chg_block(delta, dec=2, suffix="", good_when_falling=True, n_days=None):
    """Delta versus the PREVIOUS OFFICIAL PRINT. Colour follows what the move
    means for risk assets, not merely up/down."""
    if delta is None:
        return '<div class="chg flat">tidak ada cetakan sebelumnya</div>'
    if abs(delta) < 1e-9:
        return '<div class="chg flat">= tidak berubah dari cetakan sebelumnya</div>'
    arrow = "▲" if delta > 0 else "▼"
    falling = delta < 0
    cls = "dn" if (falling == good_when_falling) else "up"   # dn renders green, up renders red
    gap = f" · {n_days} hari" if n_days else ""
    return (f'<div class="chg {cls}">{arrow} {idnum(f"{delta:+,.{dec}f}")}{suffix} '
            f'<span style="font-weight:400;color:var(--muted)">vs cetakan lalu{gap}</span></div>')


_BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
          "Agustus", "September", "Oktober", "November", "Desember"]


def asof_block(iso, freq_label, kind="daily"):
    """For daily series the observation date IS roughly the real-world date, so
    'N hari lalu' is meaningful. For monthly and quarterly series it is the start
    of the reference PERIOD, not the release date, so counting days from it
    overstates staleness badly (June PCE is published end of July, not in June).
    Those get a period label instead."""
    if not iso:
        return "—"
    dt = datetime.strptime(iso, "%Y-%m-%d").date()
    if kind == "monthly":
        head = f"data bulan {_BULAN[dt.month - 1]} {dt.year}"
    elif kind == "quarterly":
        head = f"data kuartal Q{(dt.month - 1)//3 + 1} {dt.year}"
    elif kind == "weekly":
        head = f"minggu {iso}"
    else:
        age = days_ago(iso)
        head = f"per {iso}" + (f" · {age} hari lalu" if age > 0 else " · hari ini")
    return f"{head}<br><span style='opacity:.75'>{freq_label}</span>"


def build_html(S, d, R, cg, manual, errors, pulled_at, newly_printed, refresh=None):
    P = []
    A = P.append

    A(f"""<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Macro Dashboard</title>
<style>{CSS}</style>
</head>
<body>
<div class="top"><div class="wrap">
<h1>Dashboard Makro → Aset Beresiko</h1>
<p class="sub">Ditarik {pulled_at} WIB · 39 seri otomatis dari FRED &amp; CoinGecko,
sisanya riset manual bertanggal · setiap angka membawa tanggal cetakannya sendiri</p>
</div></div>
<nav><div class="navin">
<a href="#s01">01 Yang berubah</a><a href="#s02">02 Paling penting</a>
<a href="#s03">03 Obligasi</a><a href="#s04">04 Inflasi</a>
<a href="#s05">05 Tenaga kerja</a><a href="#s06">06 Likuiditas</a>
<a href="#s07">07 Selera risiko</a><a href="#s08">08 Fed</a>
<a href="#s09">09 Kalender</a><a href="#s10">10 Aturan</a>
</div></nav>
<div class="wrap">""")

    # ---------------- automation health ----------------
    if refresh and not refresh.get("manual_ok", False):
        A(f'<div class="note"><strong>Perhatian: data riset manual TIDAK berhasil di-refresh '
          f'pada percobaan terakhir ({esc(refresh.get("last_attempt", "?"))}).</strong><br>'
          f'{esc(refresh.get("manual_detail", ""))}<br><br>'
          f'Artinya angka otomatis di halaman ini (FRED dan CoinGecko) tetap segar, tapi '
          f'kalender, peluang Fed, posisi crypto dan BI rate masih memakai angka lama. '
          f'Bagian yang sudah lewat batas umurnya akan bertanda BASI di tempatnya '
          f'masing-masing.</div>')
    elif refresh and refresh.get("manual_ok"):
        A(f'<p class="sub" style="margin:-.5rem 0 1.2rem">Riset manual terakhir berhasil '
          f'di-refresh {esc(refresh.get("last_attempt", "?"))}'
          + (f' · {esc(refresh.get("manual_detail", ""))}' if refresh.get("manual_detail") else '')
          + '</p>')

    # ---------------- verdict banner ----------------
    corr = R["corr"]
    corr_txt = idnum(f"{corr:+.2f}") if corr is not None else "—"
    A('<div class="banner">')
    A(f'<p class="big">Rezim pasar sekarang</p>')
    A(f"<p><strong>Penggerak:</strong> {esc(R['driver_note'])} "
      f"<span style='color:var(--muted)'>(korelasi saham vs yield 10y, 20 hari: {corr_txt})</span></p>")
    A(f"<p><strong>Ketenagakerjaan:</strong> {esc(R['labor_note'])}</p>")
    A(f"<p><strong>Selera risiko:</strong> {esc(R['credit_note'])}</p>")

    pills = []
    cs = d.get("curve_shape")
    if cs:
        pills.append(f'<span class="pill {cs[2]}">Kurva: {esc(cs[0])}</span>')
    if R["oas"] is not None:
        pills.append(f'<span class="pill {"good" if R["credit"]=="calm" else "warn"}">HY OAS {idnum(f"{R["oas"]:.2f}")}%</span>')
    if d.get("sahm") is not None:
        pills.append(f'<span class="pill {"good" if d["sahm"]<0.5 else "bad"}">Sahm {idnum(f"{d["sahm"]:+.2f}")} / ambang 0,50</span>')
    if d.get("net_liquidity") is not None:
        pills.append(f'<span class="pill neutral">Net liquidity ${idnum(f"{d["net_liquidity"]:.3f}")} T</span>')
    A(f'<div class="pillrow">{"".join(pills)}</div>')
    A("</div>")

    # ---------------- what changed ----------------
    A('<h2 id="s01"><span class="n">01</span>Yang berubah sejak refresh terakhir</h2>')
    if newly_printed is None:
        A('<p class="h2sub">Ini run pertama, jadi belum ada pembanding. Mulai run berikutnya, '
          'kotak ini cuma menampilkan seri yang benar-benar dapat cetakan resmi baru.</p>')
    elif not newly_printed:
        A('<p class="h2sub">Tidak ada satu pun seri yang menerbitkan cetakan baru sejak refresh '
          'terakhir. Semua angka di bawah sama persis dengan sebelumnya, dan itu memang benar, '
          'bukan bug.</p>')
    else:
        A('<p class="h2sub">Cuma seri di bawah ini yang punya cetakan resmi baru. Sisanya tidak '
          'berubah karena memang belum ada rilis baru.</p>')
        A('<div class="scroll"><table><tr><th>Seri</th><th>Cetakan baru</th>'
          '<th class="num">Nilai</th><th class="num">Perubahan</th></tr>')
        for it in newly_printed:
            dv = idnum(f'{it["delta"]:+,.3f}') if it["delta"] is not None else "—"
            A(f'<tr><td>{esc(it["label"])}</td><td>{it["date"]}</td>'
              f'<td class="num">{idnum(format(it["value"], ",.3f"))}</td>'
              f'<td class="num">{dv}</td></tr>')
        A("</table></div>")

    # ---------------- tier 1 tiles ----------------
    A('<h2 id="s02"><span class="n">02</span>Yang paling penting</h2>')
    A('<p class="h2sub">Warna = artinya untuk aset beresiko, bukan sekadar naik atau turun. '
      'Hijau ramah, merah menekan.</p>')
    A('<div class="legend">Tiap kotak punya <b>dua</b> angka perubahan, dan wajar kalau keduanya '
      'berbeda arah:<br>'
      '<b>1 · Panah besar</b> = perubahan dari <b>cetakan resmi sebelumnya</b>. Kalau lembaga '
      'resminya belum merilis apa-apa, angka ini tidak bergerak sama sekali, dan itu memang benar.<br>'
      '<b>2 · Tren 20 hari</b> = arah jangka menengah. <b>Ini yang menentukan warna garis kiri</b>, '
      'supaya warnanya tidak berkedip-kedip cuma karena satu hari yang berisik.<br>'
      'Jadi garis hijau di sebelah panah merah artinya: turun selama sebulan terakhir, tapi naik '
      'di cetakan paling akhir.</div>')
    A('<div class="tiles">')

    def S_(sid):
        return S.get(sid)

    def add(sid, label, dec, suffix, freq, means, good_when_falling=True, scale=1.0,
            kind="daily"):
        s = S_(sid)
        if not s:
            A(tile(label, "gagal", "", "seri tidak berhasil ditarik", "Cek bagian 09.", "fail"))
            return
        cur = s[-1][1] * scale
        pv = s[-2][1] * scale if len(s) > 1 else None
        delta = (cur - pv) if pv is not None else None
        gap = None
        if len(s) > 1:
            gap = (datetime.strptime(s[-1][0], "%Y-%m-%d")
                   - datetime.strptime(s[-2][0], "%Y-%m-%d")).days
        chg20 = change_over(s, 20)
        if chg20 is not None:
            chg20 *= scale
        v = score_dir(chg20 if chg20 is not None else delta,
                      good_when_falling=good_when_falling, dead=0.0)
        A(tile(label, fmt(cur, dec, suffix),
               chg_block(delta, dec, suffix, good_when_falling, gap),
               asof_block(s[-1][0], freq, kind), means, v,
               trend_block(chg20, dec, suffix, good_when_falling),
               spark(s, 60, good_when_falling)))

    add("DFEDTARU", "Suku bunga Fed (batas atas)", 2, "%", "harian · target FOMC",
        "Harga uang paling dasar. Semua yield lain digantung dari sini.")

    add("DGS2", "Yield 2 tahun", 2, "%", "harian · lag ~2 hari",
        "Cerminan ekspektasi kebijakan Fed 1-2 tahun ke depan. Kalau ini naik, pasar sedang "
        "menghargai kenaikan bunga.")

    add("DGS10", "Yield 10 tahun", 2, "%", "harian · lag ~2 hari",
        "Benchmark global. Campuran pertumbuhan, inflasi, dan premi jangka. Perlu dipecah dulu "
        "sebelum dinilai, lihat bagian 03.")

    add("DGS30", "Yield 30 tahun", 2, "%", "harian · lag ~2 hari",
        "Paling sedikit soal Fed, paling banyak soal kepercayaan fiskal dan banjir penerbitan utang.")

    add("DFII10", "Yield RIIL 10 tahun", 2, "%", "harian · lag ~2 hari",
        "Yield nominal dikurangi ekspektasi inflasi. INI angka paling penting di seluruh halaman "
        "untuk crypto dan emas. Naik = uang benar-benar jadi mahal.")

    add("THREEFYTP10", "Term premium 10 tahun", 2, "%", "harian · lag ~10 hari",
        "Bagian yield yang bukan soal Fed. Ini kompensasi risiko memegang utang panjang. Naiknya "
        "angka ini yang bikin kenaikan yield jadi beracun, bukan sehat.")

    add("CPILFESL", "Core CPI (YoY)", 2, "%", "bulanan · rilis ~tgl 11", kind="monthly",
        means=
        "Inflasi tanpa energi dan pangan. Ini yang direaksi Fed, karena suku bunga tidak bisa "
        "memproduksi minyak.")

    add("PCEPILFE", "Core PCE (YoY)", 2, "%", "bulanan · rilis akhir bulan", kind="monthly",
        means=
        "Target RESMI Fed, bukan CPI. Kalau ini dan core CPI berbeda arah, yang menang PCE.")

    add("DCOILWTICO", "Minyak WTI", 2, "", "harian · lag ~1 minggu",
        "Guncangan pasokan itu stagflasioner: inflasi naik sekaligus pertumbuhan turun, jadi "
        "obligasi dan saham kena bareng. FRED tertinggal seminggu, jangan dipercaya di hari keputusan.")

    add("A191RL1Q225SBEA", "GDP riil (QoQ tahunan)", 1, "%", "kuartalan · paling lambat",
        "Paling terlambat dari semua data di sini. Berguna sebagai konfirmasi, bukan sinyal.",
        good_when_falling=(R["driver"] == "rates"), kind="quarterly")

    add("DTWEXBGS", "Indeks dolar (broad Fed)", 2, "", "harian · lag ~3 hari",
        "Bukan DXY. Ini indeks dolar versi Fed, bobotnya lebih luas. Dolar kuat = kondisi "
        "keuangan global mengetat = jelek untuk crypto dan emerging market.")

    # USDT dominance from CoinGecko
    if cg:
        A(tile("USDT dominance", f"{cg['usdt_dominance']:.2f}%",
               '<div class="chg flat">real-time, tanpa cetakan sebelumnya</div>',
               asof_block(cg["as_of"], "real-time · CoinGecko"),
               "Porsi uang crypto yang parkir di stablecoin. Naik = orang keluar dari risiko "
               "tapi belum keluar dari crypto. Turun = uang itu dibelanjakan ke aset beresiko.",
               "neutral"))
        A(tile("Bitcoin", f"${cg['btc_price']:,.0f}",
               f'<div class="chg {"dnb" if cg["btc_chg24h"]<0 else "upg"}">'
               f'{"▲" if cg["btc_chg24h"]>0 else "▼"} {cg["btc_chg24h"]:+.2f}% '
               f'<span style="font-weight:400;color:var(--muted)">24 jam</span></div>',
               asof_block(cg["as_of"], "real-time · CoinGecko"),
               "Sisi aset. Ada di sini supaya bacaan makro di atas bisa dinilai benar atau salah "
               "belakangan, bukan cuma jadi cerita.", "neutral"))
    A("</div>")
    ov, ovv = analyse_overall(S, d, R, cg)
    A(concl(ov, ovv))

    # ---------------- bonds deep dive ----------------
    A('<h2 id="s03"><span class="n">03</span>Obligasi, yield, dan premi</h2>')
    A('<p class="h2sub">Bagian ini menjawab satu pertanyaan: kenaikan yield yang sedang terjadi '
      'itu jenis yang sehat atau yang beracun? Jawabannya ada di kotak tepat di bawah ini, '
      'bukan disuruh cari sendiri.</p>')
    bond_txt, bond_v = analyse_bonds(S, d, R)
    A(concl(bond_txt, bond_v, "Jawabannya: searah atau berlawanan?"))

    A('<details open><summary>Bentuk kurva sekarang</summary><div class="dbody">')
    if cs:
        A(f"<p><strong>{esc(cs[0])}.</strong> {esc(cs[1])}</p>")
    A('<div class="scroll"><table><tr><th>Spread</th><th class="num">Sekarang</th>'
      '<th>Artinya</th></tr>')
    for key, lbl, why in [
        ("2s10s", "2y → 10y", "Ukuran kemiringan klasik. Negatif = inverted, historis sinyal resesi."),
        ("5s30s", "5y → 30y", "Fokus ke ujung panjang. Melebar biasanya cerita fiskal/premi jangka."),
        ("3m10y", "3bln → 10y", "Versi yang paling dipercaya periset Fed sebagai indikator resesi."),
    ]:
        if key in d:
            A(f'<tr><td>{lbl}</td><td class="num">{d[key]:+.0f} bps</td><td>{why}</td></tr>')
    A("</table></div>")

    if d.get("d2_20") is not None:
        A('<p style="margin-top:1rem"><strong>Ujung mana yang sebenarnya bergerak</strong> '
          '(perubahan 20 hari terakhir):</p>')
        A('<div class="scroll"><table><tr><th>Tenor</th><th class="num">Perubahan 20 hari</th></tr>')
        for key, lbl in [("d2_20", "2 tahun"), ("d10_20", "10 tahun"), ("d30_20", "30 tahun")]:
            if d.get(key) is not None:
                A(f'<tr><td>{lbl}</td><td class="num">{d[key]:+.0f} bps</td></tr>')
        A("</table></div>")
        A('<p style="color:var(--muted);font-size:.85rem">Ini tabel terpenting di bagian ini. '
          'Kalau CPI keluar panas, yang meledak duluan 2 tahun. Kalau lelang Treasury 30 tahun '
          'sepi peminat, yang meledak 30 tahun sementara 2 tahun diam. Berita utamanya sama-sama '
          '"yield naik", artinya untuk portofoliomu jauh berbeda.</p>')

    A('<p style="color:var(--muted);font-size:.85rem">Kamus: <em>bull</em> = level yield turun, '
      '<em>bear</em> = level naik. <em>Steepener</em> = spread melebar, <em>flattener</em> = '
      'menyempit. <em>Twist</em> = dua ujung bergerak berlawanan, jadi tidak bisa disebut bull '
      'maupun bear.</p>')
    A("<ul>"
      "<li><strong>Bull steepener</strong> · ujung pendek turun lebih cepat. Pemotongan bunga "
      "sedang dihargai. Awalnya risk-on, tapi sering juga sinyal resesi mendekat.</li>"
      "<li><strong>Bear steepener</strong> · ujung panjang naik. Premi jangka dan fiskal. Jelek.</li>"
      "<li><strong>Bear flattener</strong> · ujung pendek naik. Kenaikan bunga sedang dihargai. "
      "Jelek untuk growth dan crypto.</li>"
      "<li><strong>Bull flattener</strong> · ujung panjang turun. Campuran, sering karena "
      "ekspektasi pertumbuhan melemah.</li></ul>")
    A("</div></details>")

    A('<details><summary>Pecah yield 10 tahun: sehat atau beracun?</summary><div class="dbody">')
    A("<p>Yield nominal itu penjumlahan. Kalau tidak dipecah, kamu tidak bisa tahu kenaikannya "
      "jenis apa:</p>")
    A('<div class="scroll"><table><tr><th>Komponen</th><th class="num">Nilai</th>'
      '<th class="num">Per tanggal</th><th>Kalau naik</th></tr>')
    for sid, lbl, mean in [
        ("DGS10", "Yield nominal 10y", "hasil penjumlahan di bawah"),
        ("DFII10", "→ Yield riil (TIPS)", "Uang jadi mahal. Menekan semua aset beresiko, paling keras ke crypto."),
        ("T10YIE", "→ Ekspektasi inflasi (breakeven)", "Pasar mulai tidak percaya inflasi terkendali. Kalau tembus 3%, seluruh kalkulasi Fed berubah."),
        ("THREEFYTP10", "→ Term premium", "Murni harga risiko: defisit, penerbitan utang, kredibilitas fiskal. Ini yang paling beracun."),
    ]:
        s = S_(sid)
        if s:
            A(f'<tr><td>{lbl}</td><td class="num">{idnum(f"{s[-1][1]:.2f}")}%</td>'
              f'<td class="num">{s[-1][0]}</td><td>{mean}</td></tr>')
    A("</table></div>")
    A("<p><strong>Contoh nyata dari vault ini, 17 Agustus 2026:</strong> yield 30 tahun menembus "
      "5,31%, tertinggi sejak 2007, <em>padahal peluang hike September datar di sekitar 30%</em>. "
      "Jadi penyebabnya bukan jalur suku bunga sama sekali, tapi penerbitan utang besar-besaran, "
      "defisit, tarif, dan biaya energi dari kebuntuan Hormuz. Itu tipe kenaikan yield paling "
      "beracun untuk aset beresiko, karena bukan cerita pertumbuhan, murni harga risiko.</p>")
    A("<p><strong>Kebalikannya:</strong> yield naik karena pertumbuhan kuat justru bisa dibarengi "
      "saham naik dan spread kredit menyempit. Itu rezim <em>good news is good news</em>. "
      "Tes cepatnya cuma satu pertanyaan: <strong>hari ini saham dan yield searah atau berlawanan?</strong> "
      "Searah = pasar sedang dikendarai pertumbuhan. Berlawanan = dikendarai discount rate.</p>")
    A("</div></details>")

    A('<details><summary>Apa yang menggerakkan tiap tenor</summary><div class="dbody">')
    A('<div class="scroll"><table><tr><th>Tenor</th><th class="num">Sekarang</th>'
      '<th>Digerakkan terutama oleh</th></tr>')
    for sid, lbl, drv in [
        ("DGS3MO", "T-Bill 3 bulan", "Hampir murni suku bunga Fed saat ini. Nyaris tidak punya opini sendiri, dia mengikuti."),
        ("DGS2", "2 tahun", "Ekspektasi Fed 1-2 tahun ke depan. Paling reaktif ke data inflasi, data tenaga kerja, dan omongan pejabat Fed."),
        ("DGS5", "5 tahun", "Titik paling sensitif ke perubahan jalur kebijakan jangka menengah."),
        ("DGS10", "10 tahun", "Campuran pertumbuhan + inflasi + premi jangka. Benchmark yang dipakai menghargai hampir semua aset."),
        ("DGS30", "30 tahun", "Paling sedikit soal Fed. Didorong defisit, ukuran lelang, hasil lelang, dan kredibilitas fiskal jangka panjang."),
    ]:
        s = S_(sid)
        val = idnum(f"{s[-1][1]:.2f}") + "%" if s else "—"
        A(f'<tr><td><strong>{lbl}</strong></td><td class="num">{val}</td><td>{drv}</td></tr>')
    A("</table></div>")
    A("<p>Jadi kalau CPI keluar panas: yang meledak duluan 2 tahun. Kalau lelang Treasury 30 tahun "
      "sepi peminat: yang meledak 30 tahun sementara 2 tahun diam. Dua kejadian itu punya arti "
      "yang sangat berbeda untuk portofoliomu, walaupun berita utamanya sama-sama 'yield naik'.</p>")
    A("</div></details>")

    # ---------------- inflation ----------------
    A('<h2 id="s04"><span class="n">04</span>Inflasi</h2>')
    A('<p class="h2sub">Current di kiri, dan perkiraan arah berikutnya di kanan.</p>')
    A('<div class="tiles">')
    for sid, lbl, mean in [
        ("CPIAUCSL", "Headline CPI (YoY)", "Termasuk energi dan pangan. Berisik. Ini yang dikutip media."),
        ("CPILFESL", "Core CPI (YoY)", "Tanpa energi dan pangan. Ini yang direaksi Fed."),
        ("PCEPI", "Headline PCE (YoY)", "Versi BEA. Bobot beda dari CPI dan memperbolehkan substitusi."),
        ("PCEPILFE", "Core PCE (YoY)", "TARGET RESMI Fed. Kalau bertentangan dengan core CPI, ini yang menang."),
    ]:
        s = S_(sid)
        if not s:
            continue
        cur, pv = s[-1][1], (s[-2][1] if len(s) > 1 else None)
        delta = cur - pv if pv is not None else None
        A(tile(lbl, f"{cur:.2f}%", chg_block(delta, 2, "pp", True, 30),
               asof_block(s[-1][0], "bulanan", "monthly"), mean,
               score_dir(delta, True, 0.02)))
    A("</div>")

    if d.get("core_gap") is not None:
        A(f'<div class="note"><strong>Ketegangan yang belum selesai: core PCE '
          f'{S_("PCEPILFE")[-1][1]:.2f}% vs core CPI {S_("CPILFESL")[-1][1]:.2f}%, '
          f'selisih {d["core_gap"]:+.2f} poin.</strong> Kalau kamu baca CPI, Fed terlihat hampir '
          f'menang melawan inflasi. Kalau kamu baca PCE, inflasi masih jauh di atas target dan '
          f'argumen kenaikan bunga jauh lebih hidup. PCE yang jadi target resmi. Ini gap terbesar '
          f'yang belum terselesaikan di vault ini.</div>')

    inf_txt, inf_v, comps = analyse_inflation(S, d)
    if comps:
        A('<h3 class="h3">Apa yang sebenarnya mendorong angka itu</h3>')
        A('<p class="h2sub">CPI bukan satu angka, dia keranjang belanja. Ini isi keranjangnya, '
          'diurutkan dari yang paling menekan ke atas. Kolom terakhir memberi tahu komponen itu '
          'sedang memanas atau mendingin selama 3 bulan terakhir.</p>')
        A('<div class="scroll"><table><tr><th>Komponen</th><th class="num">YoY</th>'
          '<th class="num">Tren 3 bulan</th><th>Perannya</th></tr>')
        peran = {
            "Energi": "Paling liar, bisa naik-turun puluhan persen. Ini yang bikin headline beda "
                      "jauh dari core. Fed sengaja mengabaikannya karena suku bunga tidak bisa "
                      "menambah pasokan minyak.",
            "Pangan": "Ikut guncangan cuaca dan komoditas. Terasa banget di dompet, tapi bukan "
                      "yang dipakai Fed mengambil keputusan.",
            "Sewa/tempat tinggal": "Bobotnya paling besar di keranjang dan paling lambat bergerak. "
                      "Kalau ini masih tinggi, core tidak bisa turun cepat walaupun minyak jatuh.",
            "Jasa (di luar energi)": "Bagian paling lengket, digerakkan upah. Ini yang benar-benar "
                      "dipelototi pejabat Fed, sering disebut supercore.",
            "Barang inti": "Barang non-pangan non-energi. Biasanya yang pertama selesai berinflasi "
                      "setelah rantai pasok normal.",
            "Kesehatan": "Bergerak lambat, bobotnya jauh lebih besar di PCE daripada di CPI. Ini "
                      "salah satu sebab kenapa dua ukuran itu bisa berbeda.",
        }
        for lbl, val, ch3 in sorted(comps, key=lambda x: -x[1]):
            trend = ("memanas" if (ch3 or 0) > 0.2 else "mendingin" if (ch3 or 0) < -0.2 else "datar")
            tcls = "bad" if trend == "memanas" else "good" if trend == "mendingin" else "neutral"
            A(f'<tr><td><strong>{lbl}</strong></td><td class="num">{idnum(f"{val:+.2f}")}%</td>'
              f'<td class="num"><span class="tag {tcls}">{trend}</span></td>'
              f'<td>{esc(peran.get(lbl, ""))}</td></tr>')
        A("</table></div>")
    A(concl(inf_txt, inf_v))

    A('<details><summary>Apa yang menentukan cetakan inflasi berikutnya</summary><div class="dbody">')
    A("<p>Karena FedWatch tidak menerbitkan ramalan CPI, ini analisa dari komponen pembentuknya:</p>")
    brent, wti = S_("DCOILBRENTEU"), S_("DCOILWTICO")
    if brent:
        b_now = brent[-1][1]
        b_20 = value_n_back(brent, 20)
        b_250 = value_n_back(brent, 250)
        A("<ul>")
        A(f"<li><strong>Energi</strong> · Brent {b_now:.2f} per {brent[-1][0]}. "
          + (f"20 hari lalu {b_20:.2f} ({b_now-b_20:+.2f}). " if b_20 else "")
          + (f"Setahun lalu sekitar {b_250:.2f}, jadi basis tahunannya {(b_now/b_250-1)*100:+.1f}%. " if b_250 else "")
          + "Yang masuk CPI itu <strong>rata-rata bulanan terhadap bulan yang sama tahun lalu</strong>, "
            "bukan level spot dan bukan lonjakan sesaat. Lonjakan yang bolak-balik dalam seminggu "
            "hampir tidak menggerakkan angka bulanan.</li>")
        A("<li><strong>Jasa dan sewa</strong> · komponen paling lengket dan paling menentukan core. "
          "Bergerak lambat, jadi perubahan mendadak di core biasanya bukan dari sini.</li>")
        A("<li><strong>Upah</strong> · lihat average hourly earnings di bagian 05. Kalau upah "
          "melandai, tekanan ke inflasi jasa ikut melandai dengan jeda beberapa bulan.</li>")
        A("<li><strong>Ekspektasi</strong> · breakeven 10 tahun "
          + (f"{S_('T10YIE')[-1][1]:.2f}% " if S_("T10YIE") else "")
          + "dan 5y5y forward "
          + (f"{S_('T5YIFR')[-1][1]:.2f}%. " if S_("T5YIFR") else "")
          + "Selama dua angka ini menempel di sekitar 2%, pasar menganggap lonjakan inflasi "
            "bersifat sementara, dan itulah yang mengizinkan Fed menahan bunga. Kalau keduanya "
            "merangkak ke 3%, seluruh kalkulasi berbalik ke arah kenaikan bunga apapun penyebab "
            "inflasinya.</li>")
        A("</ul>")
    A("<p><strong>Peringatan lag:</strong> seri minyak FRED tertinggal sekitar seminggu dari "
      "waktu nyata. Vault ini pernah salah baca justru karena itu pada 29 Juli 2026, waktu "
      "seluruh cerita berbalik di dalam minggu yang tidak terlihat. Jangan pernah pakai angka "
      "minyak dari sini di hari keputusan Fed tanpa cek berita.</p>")
    A("</div></details>")

    # ---------------- labor + growth ----------------
    A('<h2 id="s05"><span class="n">05</span>Ketenagakerjaan &amp; pertumbuhan</h2>')
    A(f'<p class="h2sub">{esc(R["labor_note"])}</p>')
    A('<div class="tiles">')

    good_when_falling_labor = (R["labor"] == "inflation")
    s = S_("UNRATE")
    if s:
        delta = s[-1][1] - s[-2][1] if len(s) > 1 else None
        A(tile("Tingkat pengangguran", f"{s[-1][1]:.1f}%",
               chg_block(delta, 1, "pp", not good_when_falling_labor, 30),
               asof_block(s[-1][0], "bulanan", "monthly"),
               "Di rezim sekarang, pengangguran NAIK justru dibaca positif oleh aset beresiko, "
               "karena artinya Fed punya alasan melunak." if good_when_falling_labor
               else "Di rezim sekarang, pengangguran naik = resesi, dan itu jelek.",
               score_dir(delta, not good_when_falling_labor, 0.05)))
    if d.get("payems_chg") is not None:
        A(tile("Nonfarm payrolls (perubahan)", f"{d['payems_chg']:+,.0f}K",
               '<div class="chg flat">perubahan bulan ke bulan</div>',
               asof_block(d["payems_asof"], "bulanan · Jumat pertama", "monthly"),
               "Jumlah pekerjaan baru sebulan. Kuat = Fed tidak perlu melunak = jelek untuk aset "
               "beresiko di rezim sekarang.",
               "bad" if d["payems_chg"] > 150 else "good" if d["payems_chg"] < 50 else "neutral"))
    s = S_("ICSA")
    if s:
        delta = s[-1][1] - s[-2][1] if len(s) > 1 else None
        A(tile("Initial jobless claims", f"{s[-1][1]:,.0f}",
               chg_block(delta, 0, "", not good_when_falling_labor, 7),
               asof_block(s[-1][0], "MINGGUAN · tiap Kamis", "weekly"),
               "Data ketenagakerjaan paling cepat yang ada. Kalau mau tahu duluan sebelum yang "
               "lain, ini tempatnya.",
               score_dir(delta, not good_when_falling_labor, 5000)))
    s = S_("CES0500000003")
    if s:
        delta = s[-1][1] - s[-2][1] if len(s) > 1 else None
        A(tile("Pertumbuhan upah (YoY)", f"{s[-1][1]:.2f}%",
               chg_block(delta, 2, "pp", True, 30), asof_block(s[-1][0], "bulanan", "monthly"),
               "Jalur utama inflasi jasa. Upah melandai = tekanan inflasi ikut melandai.",
               score_dir(delta, True, 0.05)))
    if d.get("sahm") is not None:
        A(tile("Sahm Rule", f"{d['sahm']:+.2f}",
               f'<div class="chg flat">ambang resesi 0,50 · jarak {d["sahm_gap"]:+.2f}</div>',
               asof_block(S_("SAHMREALTIME")[-1][0], "bulanan", "monthly"),
               "Kalau rata-rata 3 bulan pengangguran naik 0,50 poin di atas titik terendah 12 "
               "bulan, secara historis resesi sudah dimulai. Angka ini yang membalik arti seluruh "
               "blok ketenagakerjaan.",
               "good" if d["sahm"] < 0.50 else "bad"))
    s = S_("A191RL1Q225SBEA")
    if s:
        delta = s[-1][1] - s[-2][1] if len(s) > 1 else None
        A(tile("GDP riil (QoQ tahunan)", f"{s[-1][1]:.1f}%",
               chg_block(delta, 1, "pp", R["driver"] == "rates", 90),
               asof_block(s[-1][0], "KUARTALAN · paling lambat", "quarterly"),
               "Paling terlambat dari semua. Untuk gambaran real-time, pakai Atlanta Fed GDPNow.",
               "neutral"))
    A("</div>")
    lab_txt, lab_v = analyse_labor(S, d, R)
    A(concl(lab_txt, lab_v))
    A('<p style="color:var(--muted);font-size:.85rem;margin-top:.9rem">Urutan ketepatan waktu: '
      '<strong>Initial Claims</strong> (mingguan) → <strong>NFP</strong> (Jumat pertama) → '
      '<strong>Unemployment Rate</strong> → <strong>JOLTS</strong>. Abaikan ADP, korelasinya ke '
      'NFP payah.</p>')

    # ---------------- liquidity ----------------
    A('<h2 id="s06"><span class="n">06</span>Likuiditas</h2>')
    A('<p class="h2sub">Suku bunga itu <em>harga</em> uang. Likuiditas itu <em>jumlah</em>-nya. '
      'Untuk crypto, jumlah sering lebih menentukan daripada harga.</p>')
    A('<div class="tiles">')
    for sid, lbl, scale, dec, suffix, freq, mean, gwf in [
        ("WALCL", "Neraca Fed", 1/1e6, 3, " T", "MINGGUAN · rilis Kamis",
         "Total aset Fed. Naik = QE (uang dicetak masuk sistem). Turun = QT (uang ditarik keluar).", False),
        ("WTREGEN", "TGA (kas pemerintah AS)", 1/1e6, 3, " T", "MINGGUAN",
         "Rekening kas Treasury. TERISI = uang tersedot keluar dari sistem = risk-off. "
         "DIKURAS = likuiditas mengalir masuk ke pasar.", True),
        ("RRPONTSYD", "Reverse Repo (RRP)", 1/1e3, 3, " T", "harian · lag ~1 hari",
         "Uang yang parkir semalaman di Fed. Turun = uang keluar dari parkiran menuju pasar.", True),
    ]:
        s = S_(sid)
        if not s:
            continue
        cur = s[-1][1] * scale
        delta = (s[-1][1] - s[-2][1]) * scale if len(s) > 1 else None
        A(tile(lbl, fmt(cur, dec, suffix), chg_block(delta, dec, suffix, gwf),
               asof_block(s[-1][0], freq, "weekly" if "MINGGUAN" in freq else "daily"),
               mean, score_dir(delta, gwf, 0.0)))

    if d.get("net_liquidity") is not None:
        nlc = d.get("net_liquidity_chg")
        A(tile("NET LIQUIDITY (hitungan)", f"${d['net_liquidity']:.3f} T",
               chg_block(nlc, 3, " T", False) if nlc is not None else
               '<div class="chg flat">butuh dua cetakan mingguan</div>',
               asof_block(d["net_liquidity_asof"], "seturut seri paling lambat", "weekly"),
               "Neraca Fed dikurangi TGA dikurangi RRP. Proksi kasar berapa uang yang benar-benar "
               "beredar di pasar. Korelasinya dengan Bitcoin secara historis mencolok.",
               score_dir(nlc, False, 0.0) if nlc is not None else "neutral"))
    if cg:
        A(tile("Pasokan stablecoin (USDT+USDC)", f"${cg['stable_total']/1e9:,.1f} M",
               '<div class="chg flat">real-time</div>',
               asof_block(cg["as_of"], "real-time · CoinGecko"),
               "Likuiditas asli khusus crypto. Naik = uang BARU masuk ekosistem, bukan sekadar "
               "uang lama yang berputar.", "neutral"))
    A("</div>")

    rrp = S_("RRPONTSYD")
    if rrp and rrp[-1][1] < 5:
        A(f'<div class="note"><strong>Catatan penting soal RRP.</strong> Saldonya tinggal '
          f'${rrp[-1][1]:.2f} miliar per {rrp[-1][0]}, yang praktis nol. Artinya kanal '
          f'"uang keluar dari parkiran menuju pasar" yang jadi bahan bakar besar di 2023-2024 '
          f'<strong>sudah habis</strong>. Ke depan, tambahan likuiditas harus datang dari neraca '
          f'Fed atau dari TGA yang dikuras, bukan lagi dari sini. Ini hal kecil yang gampang '
          f'terlewat tapi mengubah dari mana bahan bakar berikutnya bisa muncul.</div>')

    liq_txt, liq_v = analyse_liquidity(S, d, cg)
    A(concl(liq_txt, liq_v))

    # ---------------- risk appetite + crypto positioning ----------------
    A('<h2 id="s07"><span class="n">07</span>Selera risiko &amp; posisi pasar</h2>')
    A('<p class="h2sub">Makro menjelaskan koreknya. Bagian ini menjelaskan bahan bakarnya. '
      'Ledakan besar terjadi waktu keduanya bertemu.</p>')
    A('<div class="tiles">')
    for sid, lbl, dec, suffix, mean, gwf in [
        ("BAMLH0A0HYM2", "Spread kredit high-yield", 2, "%",
         "Berapa ekstra bunga yang diminta untuk meminjamkan ke perusahaan berisiko. Melebar = "
         "pasar kredit takut. Ini pengukur selera risiko paling jujur yang ada.", True),
        ("VIXCLS", "VIX", 2, "", "Volatilitas saham yang diharapkan 30 hari ke depan.", True),
    ]:
        s = S_(sid)
        if not s:
            continue
        delta = s[-1][1] - s[-2][1] if len(s) > 1 else None
        A(tile(lbl, f"{s[-1][1]:.2f}{suffix}", chg_block(delta, dec, suffix, gwf),
               asof_block(s[-1][0], "harian"), mean, score_dir(change_over(s, 20), gwf, 0.05)))
    A("</div>")

    cp = manual.get("crypto_positioning", {})
    if cp:
        stale = days_ago(cp["as_of"]) > cp.get("stale_after_days", 3)
        A(f'<h3 style="font-size:.95rem;margin:1.6rem 0 .3rem">Posisi pasar crypto</h3>')
        A(f'<p class="h2sub">Riset manual per {cp["as_of"]}'
          + (' · <span class="stale">SUDAH BASI, perlu di-refresh</span>' if stale else '')
          + '</p>')
        A('<div class="tiles">')
        for it in cp["items"]:
            A(tile(it["label"], f'<span style="font-size:1rem">{esc(it["value"])}</span>', "",
                   f'per {cp["as_of"]}<br><span style="opacity:.75">riset manual</span>',
                   esc(it["why"]), it["verdict"]))
        A("</div>")

    pos_bits, pos_bad = [], 0
    for it in cp.get("items", []):
        if it["verdict"] == "good": pos_bits.append(f"{it['label'].lower()} mendukung")
        elif it["verdict"] == "bad":
            pos_bits.append(f"{it['label'].lower()} menekan"); pos_bad += 1
    ptxt = ["<p><strong>Kenapa kamu perlu peduli ke bagian ini.</strong> Makro menentukan arah "
            "angin. Posisi pasar menentukan seberapa keras badainya. Pergerakan raksasa hampir "
            "selalu terjadi waktu berita kecil menghantam posisi yang sudah terlalu satu sisi, "
            "bukan waktu berita besar menghantam pasar yang seimbang.</p>"]
    if pos_bits:
        ptxt.append("<p><strong>Kondisi sekarang:</strong> " + ", ".join(pos_bits) + ". "
                    + ("Likuidasi yang menumpuk di sisi long berarti yang tersapu belakangan ini "
                       "adalah pembeli, bukan penjual. Itu kebalikan dari 19-21 Agustus, waktu 92% "
                       "likuidasi adalah short dan justru itulah yang meledakkan harga ke atas. "
                       "Bahan bakar untuk short squeeze berikutnya jadi lebih tipis."
                       if pos_bad else
                       "Tidak ada sisi yang terlihat berdesakan berlebihan.") + "</p>")
    if R.get("credit") == "calm":
        ptxt.append("<p>Digabung dengan spread kredit yang masih sempit, sisi <em>selera risiko</em> "
                    "belum memberi tanda bahaya. Yang menekan datang dari sisi suku bunga, bukan "
                    "dari sisi kepercayaan.</p>")
    A(concl("".join(ptxt), "bad" if pos_bad >= 2 else "neutral"))

    A('<details><summary>Kenapa bagian ini ada: berita cuma pemicu, posisi adalah bahan bakarnya</summary><div class="dbody">')
    A("<p>Kejadian 19-21 Agustus 2026 di vault ini adalah contoh paling bersih. Treasury "
      "mengumumkan buyback obligasi jangka panjang digandakan dari $2 miliar ke $4 miliar. Yield "
      "30 tahun turun dari 5,337% ke sekitar 5,19%. Bitcoin meledak.</p>")
    A("<p><strong>Tapi keesokan harinya yield sudah balik naik dan hampir menghapus seluruh "
      "penurunannya, dan Bitcoin tetap naik $6.000 lagi.</strong> Katalisnya sudah hilang tapi "
      "efeknya jalan terus. Artinya katalis itu bukan mekanismenya.</p>")
    A("<p>Mekanismenya kelihatan di tape likuidasi: sekitar $2,7 miliar posisi short ditutup paksa "
      "dalam 24 jam, 92% dari seluruh likuidasi, dengan lebih dari $1 miliar short BTC tertutup "
      "dalam satu jam saja. Short yang ditutup paksa <em>wajib membeli</em>, tidak peduli harga.</p>")
    A("<p>Aritmetikanya juga tidak nyambung: buyback $4 miliar melawan tumpukan utang $40 triliun "
      "itu debu, analis sendiri menyebutnya sebagian besar simbolis. Berita sekecil itu tidak bisa "
      "merevaluasi aset sebesar 17%. <strong>Kalau aritmetika katalisnya tidak sampai ke "
      "aritmetika pergerakannya, selisihnya diisi arus paksaan.</strong></p>")
    A("<p>Tiga pertanyaan yang bisa kamu pakai tiap kali ada pergerakan besar: "
      "(1) berapa nilai beritanya dalam dolar, sebanding tidak dengan besar pergerakannya? "
      "(2) apa yang terposisikan masuk ke situ, cek funding, open interest, likuidasi? "
      "(3) katalisnya masih berlaku hari berikutnya? Katalis yang berbalik sementara harga jalan "
      "terus sudah terfalsifikasi sebagai penjelasan.</p>")
    A("</div></details>")

    # ---------------- Fed odds + calendar ----------------
    A('<h2 id="s08"><span class="n">08</span>Fed: sekarang vs yang dihargai pasar</h2>')
    fo = manual.get("fed_odds", {})
    if fo:
        stale = days_ago(fo["as_of"]) > fo.get("stale_after_days", 4)
        A(f'<p class="h2sub">Rapat {fo["meeting"]} · riset manual per {fo["as_of"]}'
          + (' · <span class="stale">SUDAH BASI</span>' if stale else '') + '</p>')
        A('<div class="scroll"><table><tr><th>Hasil</th><th class="num">Peluang</th>'
          '<th class="num">Rentang antar venue</th></tr>')
        for o in fo["outcomes"]:
            A(f'<tr><td>{esc(o["label"])}</td><td class="num">{o["pct"]}%</td>'
              f'<td class="num">{esc(o["range"])}%</td></tr>')
        A("</table></div>")
        A(f'<div class="note">{esc(fo["note"])}</div>')

    if d.get("real_policy_rate") is not None:
        rpr = d["real_policy_rate"]
        A(f"<p><strong>Suku bunga riil kebijakan: {idnum(f'{rpr:+.2f}')}%.</strong> Ini batas atas Fed "
          f"({idnum(format(S_('DFEDTARU')[-1][1], '.2f'))}%) dikurangi core PCE "
          f"({idnum(format(S_('PCEPILFE')[-1][1], '.2f'))}%). "
          + ("Angka setipis ini berarti kebijakan sebenarnya <strong>tidak ketat</strong> menurut "
             "ukuran target Fed sendiri. Kalau core PCE terus naik sementara bunga nominal diam, "
             "kebijakan justru <em>melonggar</em> secara pasif. Ini argumen struktural terkuat "
             "untuk kenaikan bunga, dan kebalikan dari framing 'menahan bunga itu sikap ketat'."
             if rpr < 1.0 else
             "Kebijakan berada di wilayah restriktif menurut ukuran target Fed sendiri.")
          + "</p>")

    fed_txt = []
    if fo and d.get("real_policy_rate") is not None:
        hike = next((o["pct"] for o in fo["outcomes"] if "Hike" in o["label"]), None)
        fed_txt.append(f"<p><strong>Apa artinya buat kamu.</strong> Pasar menghargai sekitar "
                       f"{hike}% kemungkinan kenaikan bunga bulan depan, artinya <em>skenario "
                       f"dasar</em> yang sudah ada di harga adalah Fed diam. Yang menggerakkan "
                       f"pasar bukan keputusannya, tapi <strong>selisih antara keputusan dan apa "
                       f"yang sudah dihargai</strong>. Hold yang sudah 95% diperkirakan hampir "
                       f"tidak menggerakkan apa-apa; nada konferensi persnya yang bekerja.</p>")
        fed_txt.append("<p><strong>Yang bikin ini rapuh:</strong> suku bunga riil kebijakan tipis "
                       "sekali, jadi menahan bunga sebenarnya bukan sikap ketat. Kalau core PCE "
                       "naik lagi sementara bunga nominal diam, kebijakan justru melonggar tanpa "
                       "Fed melakukan apa pun. Itu argumen struktural terkuat untuk kenaikan bunga, "
                       "dan pasar belum banyak menghargainya. Ini titik di mana analisa di halaman "
                       "ini berbeda dari angka pasar, dan perbedaannya sengaja tidak diratakan.</p>")
        A(concl("".join(fed_txt), "neutral", "Kesimpulan bagian ini"))

    bi = manual.get("bi", {})
    if bi:
        A('<details><summary>Bank Indonesia · kenapa mandat berbeda menghasilkan aksi berlawanan</summary><div class="dbody">')
        A(f'<p><strong>BI-Rate {bi["rate"]:.2f}%</strong> · Deposit Facility {bi["deposit_facility"]:.2f}% '
          f'· Lending Facility {bi["lending_facility"]:.2f}% · per {bi["as_of"]}</p>')
        A(f"<p>{esc(bi['note'])}</p>")
        A("<p>Ini kontras yang berguna dipahami. Fed punya mandat ganda (inflasi 2% plus lapangan "
          "kerja maksimum). BI punya tambahan mandat stabilitas rupiah, yang membawa jalur nilai "
          "tukar dan selisih suku bunga yang tidak dimiliki Fed. Rupiah lemah menaikkan harga "
          "impor dan selisih bunga yang tipis terhadap dolar mengundang arus modal keluar. Jadi BI "
          "mengetatkan ke dalam guncangan global yang sama yang Fed diamkan saja. Dunia yang sama, "
          "mandat berbeda, aksi berlawanan.</p>")
        A("</div></details>")

    A('<h2 id="s09"><span class="n">09</span>Kalender: apa yang akan menggerakkan pasar</h2>')
    A('<p class="h2sub">Yang bertanda oranye = dampak tinggi. Hitung mundur otomatis.</p>')
    A('<div class="cal">')
    today = date.today()
    for ev in manual.get("calendar", []):
        ed = datetime.strptime(ev["date"], "%Y-%m-%d").date()
        delta_d = (ed - today).days
        if delta_d < 0:
            continue
        cd = "hari ini" if delta_d == 0 else ("besok" if delta_d == 1 else f"{delta_d} hari lagi")
        A(f'<div class="ev {ev["impact"]}">'
          f'<div class="when">{ev["date"][5:]}<small>{esc(ev["time"])}</small>'
          f'<small class="cd">{cd}</small></div>'
          f'<div><div class="t">{esc(ev["title"])}</div>'
          f'<div class="w">{esc(ev["why"])}</div></div></div>')
    A("</div>")

    # ---------------- rules ----------------
    A('<h2 id="s10"><span class="n">10</span>Aturan penilaian &amp; catatan kejujuran</h2>')
    A('<details><summary>Aturan warna hijau/merah, ditulis supaya tidak bisa diubah diam-diam</summary><div class="dbody">')
    A('<div class="scroll"><table><tr><th>Metrik</th><th>Aturan</th></tr>')
    for k, v in RULES_TEXT:
        A(f"<tr><td><strong>{esc(k)}</strong></td><td>{esc(v)}</td></tr>")
    A("</table></div>")
    A("<p>Detektor rezim jalan <strong>duluan</strong>, baru tiap metrik dinilai dengan rezim itu "
      "sebagai konteks. Alasannya: data yang sama punya arti berlawanan di rezim berbeda, jadi "
      "menilai metrik tanpa menetapkan rezim dulu itu asal-asalan.</p>")
    A("<p>Warna dinilai dari perubahan <strong>20 observasi</strong> supaya tidak berkedip-kedip "
      "karena satu hari yang berisik, sementara angka delta yang ditampilkan di tiap kotak adalah "
      "perubahan versus <strong>cetakan resmi sebelumnya</strong> seperti yang kamu minta. Dua "
      "hal berbeda, keduanya ditampilkan.</p>")
    A("</div></details>")

    A('<details><summary>Batasan yang perlu kamu tahu sebelum percaya halaman ini</summary><div class="dbody">')
    A("<ul>")
    A("<li><strong>Ini alat baca, bukan sinyal trading.</strong> Semua di halaman ini kerangka "
      "penjelasan. Tidak ada satu pun yang otomatis jadi aturan yang bisa ditradingkan. Korelasi "
      "makro ke harga aset tidak stabil, berbalik tanda antar rezim, dan sudah dihargai oleh pihak "
      "yang datanya lebih cepat. Kalau sesuatu di sini mulai terasa seperti aturan yang bisa "
      "dites, aturannya: daftarkan dulu aturannya secara tertulis beserta kriteria "
      "lulusnya, baru tes. Jangan pernah mengubah kriteria setelah melihat hasil.</li>")
    A("<li><strong>Lag itu nyata dan pernah menipu vault ini.</strong> Tiap angka membawa tanggal "
      "cetakannya sendiri justru karena itu. Term premium tertinggal ~10 hari, minyak ~seminggu, "
      "GDP satu kuartal. Jangan sandingkan begitu saja seolah semuanya menggambarkan hari ini.</li>")
    A("<li><strong>CME FedWatch tidak bisa diakses dari mesin ini</strong> (dicek ulang, http=000). "
      "Kalshi API timeout. Jadi peluang hike di atas berasal dari Polymarket dan laporan pers, "
      "dikutip sebagai rentang, bukan titik. Venue-venue ini rutin tidak sepakat.</li>")
    A("<li><strong>Angka yang gagal ditarik ditampilkan sebagai gagal</strong>, tidak pernah "
      "dihilangkan diam-diam, dan tidak pernah diisi dari ingatan.</li>")
    A("</ul>")
    A("</div></details>")

    if errors:
        A('<div class="note"><strong>Seri yang gagal ditarik pada run ini:</strong><br>'
          + "<br>".join(f"<code>{esc(k)}</code> · {esc(v)}" for k, v in errors.items())
          + "<br><br>Gagal di sini berarti tidak terjangkau dari mesin ini saat ini, bukan berarti "
            "serinya mati.</div>")

    A(f'<div class="foot">Dibuat oleh <code>scripts/build_macro_dashboard.py</code> · '
      f'{pulled_at} WIB · sumber otomatis FRED + CoinGecko, sumber manual bertanggal di '
      f'<code>scripts/macro_manual.json</code> · snapshot mentah tersimpan di '
      f'<code>raw/macro-data-pulls/snapshots/</code>.<br>'
      f'Penjelasan konsep lengkap ada di halaman wiki '
      f'<code>concepts/macro-drivers-of-risk-assets.md</code>.</div>')
    A("</div>")
    A("</body>" + chr(10) + "</html>")
    return "\n".join(P)


# --------------------------------------------------------------------------
# 7 · SNAPSHOT (what enables "what changed since last refresh")
# --------------------------------------------------------------------------
def load_refresh_status():
    """Written by run-macro-update.ps1. Lets the page show when its own manual half
    failed to refresh, instead of that failure being invisible."""
    try:
        return json.loads(REFRESH_STATUS.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def load_last_snapshot():
    if not SNAP_DIR.exists():
        return None
    files = sorted(SNAP_DIR.glob("*.json"))
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except Exception:
        return None


def diff_prints(S, old):
    """Only series whose LATEST OFFICIAL PRINT DATE advanced count as changed."""
    if not old:
        return None
    prior = old.get("latest_prints", {})
    out = []
    for sid, s in S.items():
        if not s:
            continue
        cur_date, cur_val = s[-1]
        was = prior.get(sid)
        if was and was.get("date") != cur_date:
            delta = None
            try:
                delta = cur_val - float(was["value"])
            except (TypeError, ValueError, KeyError):
                pass
            out.append({"label": sid, "date": cur_date, "value": cur_val, "delta": delta})
    return out


def write_snapshot(S, d, R, cg, errors, stamp):
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "pulled_at": stamp,
        "latest_prints": {sid: {"date": s[-1][0], "value": s[-1][1]}
                          for sid, s in S.items() if s},
        "derived": {k: v for k, v in d.items() if isinstance(v, (int, float, str))},
        "regime": {k: v for k, v in R.items() if isinstance(v, (int, float, str))},
        "coingecko": cg,
        "errors": errors,
    }
    path = SNAP_DIR / f"{datetime.now().strftime('%Y-%m-%d-%H%M')}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    manual = json.loads(MANUAL.read_text(encoding="utf-8"))

    S, errors = {}, {}
    for sid, tr in FRED:
        try:
            S[sid] = fetch_fred(sid, tr)
            if args.verbose:
                print(f"  ok   {sid:18s} {S[sid][-1][0]}  {S[sid][-1][1]}")
        except Exception as e:
            errors[sid] = f"{type(e).__name__}: {e}"
            if args.verbose:
                print(f"  FAIL {sid:18s} {e}", file=sys.stderr)

    cg = None
    try:
        cg = fetch_coingecko()
        if args.verbose:
            print(f"  ok   coingecko           USDT.D {cg['usdt_dominance']:.2f}%")
    except Exception as e:
        errors["coingecko"] = f"{type(e).__name__}: {e}"

    d = derive(S)
    R = regime(S, d)

    old = load_last_snapshot()
    newly = diff_prints(S, old)
    refresh = load_refresh_status()

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = build_html(S, d, R, cg, manual, errors, stamp, newly, refresh)
    OUT_HTML.write_text(html, encoding="utf-8")
    snap = write_snapshot(S, d, R, cg, errors, stamp)

    print(f"wrote {OUT_HTML}  ({len(html):,} bytes)")
    print(f"snapshot {snap.name}")
    print(f"series ok: {len(S)}/{len(FRED)}   failed: {len(errors)}")
    if newly:
        print(f"new official prints since last run: {', '.join(i['label'] for i in newly)}")
    elif newly == []:
        print("no new official prints since last run")
    if errors:
        print("errors: " + ", ".join(errors), file=sys.stderr)


if __name__ == "__main__":
    main()
