import json,math,os,time
from datetime import datetime,timezone
import numpy as np,pandas as pd,yfinance as yf
ROOT=os.path.dirname(os.path.abspath(__file__)); ASSETS=json.load(open(os.path.join(ROOT,"assets.json"),encoding="utf-8")); DATA=os.path.join(ROOT,"data.json")
def clamp(x): return max(0.0,min(1.0,float(x)))
def RSI(s,n=14):
    s=pd.Series(s).dropna().astype(float)
    if len(s)<n+2:return None
    d=s.diff();u=d.clip(lower=0);dn=(-d.clip(upper=0));au=u.ewm(alpha=1/n,adjust=False,min_periods=n).mean();ad=dn.ewm(alpha=1/n,adjust=False,min_periods=n).mean();rs=au/ad.replace(0,np.nan);o=100-(100/(1+rs))
    return float(o.iloc[-1]) if len(o) and pd.notna(o.iloc[-1]) else None
def pct(s,v):
    s=pd.Series(s).dropna().astype(float); return float((s<=v).mean()) if len(s) else .5
def fetch(t):
    err=None
    for i in range(4):
        try:
            h=yf.download(t,period="5y",interval="1d",auto_adjust=False,progress=False,threads=False)
            if h is not None and not h.empty:return h
        except Exception as e:err=e
        time.sleep(2+i*2)
    raise RuntimeError(f"fetch failed {err}")
def analyst(t):
    try:
        info=yf.Ticker(t).info or {}; x=info.get("targetMeanPrice"); n=info.get("numberOfAnalystOpinions")
        if x and float(x)>0:return float(x),int(n or 0)
    except Exception:pass
    return None,0
def model_forecasts(close,p,risk,cls):
    s=pd.Series(close).dropna().astype(float)
    if len(s)<260:return p,p
    y=s.tail(min(len(s),730))
    years=max(1.0,(len(y)-1)/365.0)
    cagr=(max(float(y.iloc[-1]),0.05)/max(float(y.iloc[0]),0.05))**(1/years)-1
    if cls=="Crypto":
        cagr=max(-0.35,min(1.20,cagr))
        adj=(.50-risk)*.25
        one=max(p*.35,min(p*6.0,p*(1+cagr+adj)))
        two_c=max(-.25,min(1.00,cagr+adj))
        two=max(p*.25,min(p*12.0,p*((1+two_c)**2)))
        return one,two
    cap=0.60 if cls in ("Metals","Oil","Indices") else 0.50
    cagr=max(-0.30, min(cap,cagr))
    adj=(.50-risk)*(.12 if cls in ("Metals","Oil","Indices") else .10)
    one=max(p*.55,min(p*2.5,p*(1+cagr+adj)))
    two_c=max(-.20,min(cap-.05,cagr+adj))
    two=max(p*.40,min(p*4.0,p*((1+two_c)**2)))
    return one,two

def calc(a):
    t=a["yf"];cls=a["type"];h=fetch(t);c=h["Close"];c=c.iloc[:,0] if isinstance(c,pd.DataFrame) else c;c=c.dropna().astype(float);p=float(c.iloc[-1]);prev=float(c.iloc[-2]) if len(c)>1 else p;ch=(p/prev-1)*100 if prev else 0
    wrsi=RSI(c.resample("W-FRI").last().dropna(),14); hi=float(c.tail(min(len(c),1095)).max());lo=float(c.tail(min(len(c),1095)).min());dd=(p/hi-1)*100 if hi else 0;pos=(p-lo)/(hi-lo) if hi>lo else .5
    ret=c.pct_change().dropna();ann=365 if cls=="Crypto" else 252;vol=float(ret.tail(30).std()*math.sqrt(ann)) if len(ret)>=30 else 0;vr=pct(ret.rolling(30).std().dropna()*math.sqrt(ann),vol);w=wrsi if wrsi is not None else 50
    if cls=="Crypto":
        ma=c.rolling(730,min_periods=min(365,len(c))).mean().iloc[-1]; ld=math.log(max(p,1e-9)/max(float(ma),1e-9)) if pd.notna(ma) else 0;trend=clamp((ld+.55)/1.35);rr=clamp((w-25)/60);dr=clamp(1-abs(dd)/75);risk=clamp(.40*trend+.20*pos+.15*rr+.15*dr+.10*vr);risk=clamp((risk**1.18)*.88)
    else:
        ma=c.rolling(200,min_periods=min(120,len(c))).mean().iloc[-1];dist=(p/float(ma)-1) if pd.notna(ma) and ma else 0;sig=float(ret.tail(60).std()) if len(ret)>=20 else .02;trend=clamp(((dist/max(sig*math.sqrt(200),.08))+1.25)/2.5);rr=clamp((w-25)/60);dr=clamp(1-abs(dd)/60);weights=(.34,.18,.18,.20,.10) if cls=="Metals" else (.34,.18,.18,.20,.10) if cls=="Oil" else (.36,.18,.16,.22,.08) if cls=="Indices" else (.38,.18,.16,.20,.08);risk=clamp(weights[0]*trend+weights[1]*rr+weights[2]*dr+weights[3]*pos+weights[4]*vr)
    tgt,n=(None,0) if cls in ("Crypto","Metals","Indices","Oil") else analyst(t)
    one,two=model_forecasts(c,p,risk,cls)
    if tgt:
        one=float(tgt); two=float(tgt)*1.35
        src="Analyst consensus"; basis=(f"Yahoo Finance analyst consensus ({n} analysts)" if n else "Yahoo Finance analyst consensus")
    else:
        src="Model projection"; basis="Long-term trend, cycle/risk position and momentum model"
    return p,round(risk,4),{"rsi14":None if wrsi is None else round(wrsi,2),"rsi_timeframe":"weekly","change24h":round(ch,2),"drawdown_ath":round(dd,2),"trend":round(trend,4),"volatility30":round(vol,4),"position":round(pos,4),"crystal_target":round(float(one),4),"crystal_1y":round(float(one),4),"crystal_2y":round(float(two),4),"crystal_source":src,"crystal_basis":basis,"crystal_updated":datetime.now(timezone.utc).date().isoformat(),"telescope_low":round(float(lo)*0.90,4),"telescope_high":round(float(hi)*1.10,4)}
old={}
if os.path.exists(DATA):
    try:old=json.load(open(DATA,encoding="utf-8"))
    except:old={}
out={"prices":dict(old.get("prices",{})),"risks":dict(old.get("risks",{})),"components":dict(old.get("components",{})),"errors":{},"updated":datetime.now(timezone.utc).isoformat(),"last_successful_update":old.get("last_successful_update"),"model_version":"V62"}
ok=0
for a in ASSETS:
    if not a.get("yf"): continue
    try:p,r,c=calc(a);out["prices"][a["yf"]]=p;out["risks"][a["yf"]]=r;out["components"][a["yf"]]=c;ok+=1
    except Exception as e:out["errors"][a["yf"]]=str(e)[:180]
if ok:out["last_successful_update"]=datetime.now(timezone.utc).isoformat()
json.dump(out,open(DATA,"w",encoding="utf-8"),indent=2)
print(f"updated {ok}/{len(ASSETS)}")
