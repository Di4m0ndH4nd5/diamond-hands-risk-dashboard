import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

ASSETS = json.loads(Path("assets.json").read_text())

BASES = [
    "https://query1.finance.yahoo.com/v8/finance/chart/",
    "https://query2.finance.yahoo.com/v8/finance/chart/",
]

session = requests.Session()
session.headers.update({
    "Accept": "application/json",
    "User-Agent": "Di4m0ndH4nd5-Risk-Dashboard/13"
})

def clamp01(x):
    return max(0.0, min(1.0, float(x)))

def percentile_rank(values, value):
    vals = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    if not vals:
        return 0.5
    return sum(x <= value for x in vals) / len(vals)

def ema(values, alpha):
    out = []
    e = None
    for v in values:
        if v is None:
            out.append(None)
            continue
        v = float(v)
        e = v if e is None else alpha * v + (1-alpha) * e
        out.append(e)
    return out

def rsi14(closes):
    clean = [float(x) for x in closes if x is not None]
    if len(clean) < 16:
        return 50.0
    diffs = [clean[i]-clean[i-1] for i in range(1, len(clean))]
    gains = [max(d,0.0) for d in diffs]
    losses = [max(-d,0.0) for d in diffs]
    ag = ema(gains, 1/14)[-1]
    al = ema(losses, 1/14)[-1]
    if not al:
        return 100.0 if ag and ag > 0 else 50.0
    rs = ag / al
    return 100 - (100/(1+rs))

def sma(values, window):
    out=[]
    buf=[]
    total=0.0
    for v in values:
        if v is None:
            out.append(None)
            continue
        v=float(v)
        buf.append(v); total += v
        if len(buf) > window:
            total -= buf.pop(0)
        out.append(total/len(buf) if len(buf) >= min(window,120) else None)
    return out

def yahoo_chart(symbol, range_="3y", interval="1d"):
    encoded = quote(symbol, safe="")
    last_error = None
    for base in BASES:
        url = base + encoded
        for attempt in range(3):
            try:
                r = session.get(
                    url,
                    params={
                        "range": range_,
                        "interval": interval,
                        "includePrePost": "false",
                        "events": "div,splits"
                    },
                    timeout=20
                )
                if r.status_code == 429:
                    time.sleep(2 + attempt*3)
                    continue
                r.raise_for_status()
                payload = r.json()
                result = payload.get("chart",{}).get("result")
                if not result:
                    raise RuntimeError(payload.get("chart",{}).get("error") or "No Yahoo result")
                return result[0]
            except Exception as e:
                last_error = e
                time.sleep(1 + attempt)
    raise RuntimeError(f"Yahoo Finance failed for {symbol}: {last_error}")

prices = {}
risks = {}
components = {}
errors = {}

for a in ASSETS:
    symbol = a["yf"]
    try:
        data = yahoo_chart(symbol, "3y", "1d")
        meta = data.get("meta", {})
        quote_data = (data.get("indicators",{}).get("quote") or [{}])[0]
        closes = quote_data.get("close") or []

        # Latest market price from Yahoo metadata, fallback to last daily close.
        latest = meta.get("regularMarketPrice")
        if latest is None:
            valid = [x for x in closes if x is not None]
            latest = valid[-1] if valid else None
        if latest is None:
            raise RuntimeError("No current price")
        latest = float(latest)

        # Replace latest daily close with current market price so intraday movement
        # can influence the hourly risk score.
        calc = [float(x) if x is not None else None for x in closes]
        if calc:
            last_valid = max(i for i,v in enumerate(calc) if v is not None)
            calc[last_valid] = latest

        valid_calc = [x for x in calc if x is not None]
        if len(valid_calc) < 120:
            raise RuntimeError("Insufficient history for risk model")

        # 1) Price extension relative to 200-day trend.
        ma200 = sma(calc, 200)
        extensions = []
        extension_now = 1.0
        for px,ma in zip(calc,ma200):
            if px is not None and ma not in (None,0):
                extensions.append(px/ma)
                extension_now = px/ma
        trend_risk = percentile_rank(extensions, extension_now)

        # 2) RSI momentum.
        rsi_now = rsi14(calc)
        momentum_risk = clamp01(rsi_now / 100.0)

        # 3) Price percentile over available three-year history.
        price_position_risk = percentile_rank(valid_calc, latest)

        # 4) Proximity to three-year high.
        high_3y = max(valid_calc)
        high_proximity_risk = clamp01(latest/high_3y) if high_3y else 0.5

        risk = clamp01(
            0.35*trend_risk +
            0.25*momentum_risk +
            0.25*price_position_risk +
            0.15*high_proximity_risk
        )

        prices[symbol] = round(latest, 6)
        risks[symbol] = round(risk, 4)
        components[symbol] = {
            "trend_extension": round(trend_risk,4),
            "momentum_rsi": round(momentum_risk,4),
            "price_position": round(price_position_risk,4),
            "high_proximity": round(high_proximity_risk,4),
            "rsi14": round(rsi_now,2),
            "price_vs_200dma": round(extension_now,4),
            "currency": meta.get("currency"),
            "exchange": meta.get("exchangeName"),
            "market_state": meta.get("marketState")
        }
        print(f"{symbol}: {latest} risk={risk:.4f}")

    except Exception as e:
        errors[symbol] = str(e)
        print(f"ERROR {symbol}: {e}")

# Preserve the last good value for an asset if Yahoo temporarily fails,
# rather than making the dashboard blank.
data_path = Path("data.json")
if data_path.exists():
    try:
        old = json.loads(data_path.read_text())
        for symbol,value in old.get("prices",{}).items():
            prices.setdefault(symbol,value)
        for symbol,value in old.get("risks",{}).items():
            risks.setdefault(symbol,value)
        for symbol,value in old.get("components",{}).items():
            components.setdefault(symbol,value)
    except Exception:
        pass

data_path.write_text(json.dumps({
    "updated": datetime.now(timezone.utc).isoformat(),
    "source": "Yahoo Finance chart feed",
    "prices": prices,
    "risks": risks,
    "components": components,
    "errors": errors
}, indent=2))

# Fail the Action only if nothing at all could be refreshed.
if not prices:
    raise SystemExit("No market prices could be refreshed.")
