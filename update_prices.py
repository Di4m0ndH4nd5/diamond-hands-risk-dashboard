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
    "User-Agent": "Di4m0ndH4nd5-Risk-Dashboard/20"
})

def clamp01(x):
    return max(0.0, min(1.0, float(x)))

def percentile_rank(values, value):
    vals = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    if not vals:
        return 0.5
    return sum(x <= value for x in vals) / len(vals)

def ema(values, alpha):
    out=[]
    e=None
    for v in values:
        if v is None:
            out.append(None)
            continue
        v=float(v)
        e=v if e is None else alpha*v + (1-alpha)*e
        out.append(e)
    return out

def rsi(values, period=14):
    clean=[float(x) for x in values if x is not None]
    if len(clean) < period+2:
        return 50.0
    diffs=[clean[i]-clean[i-1] for i in range(1,len(clean))]
    gains=[max(d,0.0) for d in diffs]
    losses=[max(-d,0.0) for d in diffs]
    ag=ema(gains,1/period)[-1]
    al=ema(losses,1/period)[-1]
    if not al:
        return 100.0 if ag and ag>0 else 50.0
    rs=ag/al
    return 100.0-(100.0/(1.0+rs))

def sma(values, window, min_periods=None):
    if min_periods is None:
        min_periods=max(20, int(window*0.6))
    out=[]
    buf=[]
    total=0.0
    for v in values:
        if v is None:
            out.append(None)
            continue
        v=float(v)
        buf.append(v)
        total += v
        if len(buf)>window:
            total -= buf.pop(0)
        out.append(total/len(buf) if len(buf)>=min_periods else None)
    return out

def log_returns(values):
    clean=[float(x) if x is not None else None for x in values]
    out=[]
    prev=None
    for x in clean:
        if x is None or prev is None or prev<=0 or x<=0:
            out.append(None)
        else:
            out.append(math.log(x/prev))
        if x is not None:
            prev=x
    return out

def rolling_std(values, window=30):
    out=[]
    buf=[]
    for v in values:
        if v is None:
            out.append(None)
            continue
        buf.append(float(v))
        if len(buf)>window:
            buf.pop(0)
        if len(buf)<max(10,window//2):
            out.append(None)
            continue
        mean=sum(buf)/len(buf)
        var=sum((x-mean)**2 for x in buf)/max(1,len(buf)-1)
        out.append(math.sqrt(var))
    return out

def max_drawdown_position(values):
    clean=[float(x) for x in values if x is not None]
    if not clean:
        return 0.5, 0.0
    peak=max(clean)
    current=clean[-1]
    dd=(current/peak)-1.0 if peak>0 else 0.0
    # Map deep drawdowns to low risk, near-highs to high risk.
    # 0% drawdown => 1.0 risk, -70% or worse => ~0.0.
    risk=clamp01(1.0 + dd/0.70)
    return risk, dd

def yahoo_chart(symbol, range_="3y", interval="1d"):
    encoded=quote(symbol,safe="")
    last_error=None
    for base in BASES:
        url=base+encoded
        for attempt in range(3):
            try:
                r=session.get(
                    url,
                    params={
                        "range":range_,
                        "interval":interval,
                        "includePrePost":"false",
                        "events":"div,splits"
                    },
                    timeout=20
                )
                if r.status_code==429:
                    time.sleep(2+attempt*3)
                    continue
                r.raise_for_status()
                payload=r.json()
                result=payload.get("chart",{}).get("result")
                if not result:
                    raise RuntimeError(payload.get("chart",{}).get("error") or "No Yahoo result")
                return result[0]
            except Exception as e:
                last_error=e
                time.sleep(1+attempt)
    raise RuntimeError(f"Yahoo Finance failed for {symbol}: {last_error}")

def asset_class(a):
    t=a.get("type","")
    if t=="Crypto":
        return "crypto"
    if t=="Metal":
        return "metal"
    if t=="Index":
        return "index"
    return "stock"

def model_weights(cls):
    # Sum = 1.00 for each class.
    if cls=="crypto":
        return {
            "trend":0.30,
            "rsi":0.20,
            "drawdown":0.25,
            "position":0.15,
            "volatility":0.10,
        }
    if cls=="stock":
        return {
            "trend":0.30,
            "rsi":0.15,
            "drawdown":0.15,
            "position":0.25,
            "volatility":0.15,
        }
    if cls=="index":
        return {
            "trend":0.35,
            "rsi":0.10,
            "drawdown":0.15,
            "position":0.30,
            "volatility":0.10,
        }
    # metals
    return {
        "trend":0.35,
        "rsi":0.15,
        "drawdown":0.20,
        "position":0.20,
        "volatility":0.10,
    }

def volatility_normalised_trend(calc):
    ma200=sma(calc,200,120)
    rets=log_returns(calc)
    vol30=rolling_std(rets,30)

    z_series=[]
    z_now=0.0
    for px,ma,v in zip(calc,ma200,vol30):
        if px is None or ma in (None,0) or v in (None,0):
            continue
        # log distance to 200DMA, divided by recent daily volatility.
        z=math.log(px/ma)/v
        # Winsorise extremes so one spike doesn't dominate.
        z=max(-8.0,min(8.0,z))
        z_series.append(z)
        z_now=z

    if not z_series:
        return 0.5, 0.0
    return percentile_rank(z_series,z_now), z_now

def volatility_risk(calc):
    rets=log_returns(calc)
    vol30=rolling_std(rets,30)
    vals=[v for v in vol30 if v is not None]
    if not vals:
        return 0.5,0.0
    now=vals[-1]
    # Higher volatility than its own history raises risk.
    return percentile_rank(vals,now), now

prices={}
risks={}
components={}
errors={}

for a in ASSETS:
    symbol=a["yf"]
    try:
        data=yahoo_chart(symbol,"3y","1d")
        meta=data.get("meta",{})
        q=(data.get("indicators",{}).get("quote") or [{}])[0]
        closes=q.get("close") or []

        latest=meta.get("regularMarketPrice")
        if latest is None:
            valid=[x for x in closes if x is not None]
            latest=valid[-1] if valid else None
        if latest is None:
            raise RuntimeError("No current price")
        latest=float(latest)

        calc=[float(x) if x is not None else None for x in closes]
        if not calc:
            raise RuntimeError("No history")
        last_valid=max(i for i,v in enumerate(calc) if v is not None)
        calc[last_valid]=latest

        valid_calc=[x for x in calc if x is not None]
        if len(valid_calc)<120:
            raise RuntimeError("Insufficient history for risk model")

        cls=asset_class(a)
        w=model_weights(cls)

        # Trend extension, volatility-normalised.
        trend_risk, trend_z = volatility_normalised_trend(calc)

        # Momentum.
        rsi_now=rsi(calc,14)
        rsi_risk=clamp01(rsi_now/100.0)

        # Drawdown/cycle risk.
        drawdown_risk, drawdown_now=max_drawdown_position(valid_calc)

        # Relative price position in 3-year range.
        position_risk=percentile_rank(valid_calc,latest)

        # Volatility regime risk (relative to own history).
        vol_risk, daily_vol=volatility_risk(calc)

        risk=clamp01(
            w["trend"]*trend_risk +
            w["rsi"]*rsi_risk +
            w["drawdown"]*drawdown_risk +
            w["position"]*position_risk +
            w["volatility"]*vol_risk
        )

        prices[symbol]=round(latest,6)
        risks[symbol]=round(risk,4)
        components[symbol]={
            "asset_class":cls,
            "weights":w,
            "trend_risk":round(trend_risk,4),
            "trend_vol_z":round(trend_z,4),
            "rsi14":round(rsi_now,2),
            "rsi_risk":round(rsi_risk,4),
            "drawdown_from_3y_high":round(drawdown_now,4),
            "drawdown_risk":round(drawdown_risk,4),
            "price_position_3y":round(position_risk,4),
            "volatility_risk":round(vol_risk,4),
            "daily_volatility_30d":round(daily_vol,6),
            "currency":meta.get("currency"),
            "exchange":meta.get("exchangeName"),
            "market_state":meta.get("marketState"),
            "model_version":"V20"
        }
        print(f"{symbol}: price={latest} risk={risk:.4f} class={cls}")

    except Exception as e:
        errors[symbol]=str(e)
        print(f"ERROR {symbol}: {e}")

# Preserve last good values if one ticker temporarily fails.
data_path=Path("data.json")
if data_path.exists():
    try:
        old=json.loads(data_path.read_text())
        for symbol,value in old.get("prices",{}).items():
            prices.setdefault(symbol,value)
        for symbol,value in old.get("risks",{}).items():
            risks.setdefault(symbol,value)
        for symbol,value in old.get("components",{}).items():
            components.setdefault(symbol,value)
    except Exception:
        pass

data_path.write_text(json.dumps({
    "updated":datetime.now(timezone.utc).isoformat(),
    "source":"Yahoo Finance chart feed",
    "model_version":"V20",
    "prices":prices,
    "risks":risks,
    "components":components,
    "errors":errors
},indent=2))

if not prices:
    raise SystemExit("No market prices could be refreshed.")
