import json, math, os
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import yfinance as yf

ROOT=os.path.dirname(os.path.abspath(__file__))
ASSETS=json.load(open(os.path.join(ROOT,"assets.json"),encoding="utf-8"))

def clamp(x): return max(0.0,min(1.0,float(x)))
def rsi14(close):
    d=close.diff(); up=d.clip(lower=0); dn=(-d.clip(upper=0))
    au=up.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    ad=dn.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    rs=au/ad.replace(0,np.nan)
    out=100-(100/(1+rs))
    return float(out.iloc[-1]) if len(out) and pd.notna(out.iloc[-1]) else None

def percentile_rank(series, value):
    s=pd.Series(series).dropna()
    if len(s)==0:return .5
    return float((s<=value).mean())

def calc(asset):
    t=asset["yf"]; cls=asset["type"]
    hist=yf.download(t,period="5y",interval="1d",auto_adjust=False,progress=False,threads=False)
    if hist is None or hist.empty: raise RuntimeError("no history")
    close=hist["Close"]
    if isinstance(close,pd.DataFrame): close=close.iloc[:,0]
    close=close.dropna().astype(float)
    p=float(close.iloc[-1]); prev=float(close.iloc[-2]) if len(close)>1 else p
    change24=(p/prev-1)*100 if prev else 0.0
    rsi=rsi14(close)
    high3=float(close.tail(min(len(close),1095)).max())
    drawdown=(p/high3-1)*100 if high3 else 0.0
    low3=float(close.tail(min(len(close),1095)).min())
    pos=(p-low3)/(high3-low3) if high3>low3 else .5

    ret=close.pct_change().dropna()
    vol30=float(ret.tail(30).std()*math.sqrt(365 if cls=="Crypto" else 252)) if len(ret)>=30 else 0.0
    vol_hist=ret.rolling(30).std().dropna()*math.sqrt(365 if cls=="Crypto" else 252)
    vol_risk=percentile_rank(vol_hist,vol30) if len(vol_hist) else .5

    if cls=="Crypto":
        ma=close.rolling(730,min_periods=min(365,len(close))).mean().iloc[-1]
        logdist=math.log(max(p,1e-9)/max(float(ma),1e-9)) if pd.notna(ma) else 0
        trend=clamp((logdist+0.55)/1.35)
        # long-cycle model: trend + cycle position dominate; RSI/volatility deliberately lighter
        rsi_risk=clamp(((rsi if rsi is not None else 50)-25)/60)
        dd_risk=clamp(1-abs(drawdown)/75)
        risk=clamp(.40*trend+.20*pos+.15*rsi_risk+.15*dd_risk+.10*vol_risk)
        risk=clamp((risk**1.18)*.88)
    else:
        ma=close.rolling(200,min_periods=min(120,len(close))).mean().iloc[-1]
        dist=(p/float(ma)-1) if pd.notna(ma) and ma else 0
        sigma=float(ret.tail(60).std()) if len(ret)>=20 else .02
        z=dist/max(sigma*math.sqrt(200),.08)
        trend=clamp((z+1.25)/2.5)
        rsi_risk=clamp(((rsi if rsi is not None else 50)-25)/60)
        dd_risk=clamp(1-abs(drawdown)/60)
        if cls=="Metals":
            w=(.34,.18,.18,.20,.10)
        elif cls=="Indices":
            w=(.36,.18,.16,.22,.08)
        else:
            w=(.38,.18,.16,.20,.08)
        risk=clamp(w[0]*trend+w[1]*rsi_risk+w[2]*dd_risk+w[3]*pos+w[4]*vol_risk)

    return p, round(risk,4), {
      "rsi14": None if rsi is None else round(rsi,2),
      "change24h": round(change24,2),
      "drawdown_ath": round(drawdown,2),
      "trend": round(trend,4),
      "volatility30": round(vol30,4),
      "position": round(pos,4)
    }

out={"prices":{},"risks":{},"components":{},"errors":{},"updated":datetime.now(timezone.utc).isoformat(),"model_version":"V33"}
for a in ASSETS:
    try:
        p,r,c=calc(a); out["prices"][a["yf"]]=p; out["risks"][a["yf"]]=r; out["components"][a["yf"]]=c
    except Exception as e:
        out["errors"][a["yf"]]=str(e)[:180]
with open(os.path.join(ROOT,"data.json"),"w",encoding="utf-8") as f:
    json.dump(out,f,indent=2)
print(f'updated {len(out["prices"])}/{len(ASSETS)} assets')
