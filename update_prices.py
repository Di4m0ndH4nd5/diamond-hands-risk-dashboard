import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

assets = json.loads(Path("assets.json").read_text())
prices = {}
risks = {}
components = {}

def clamp01(x):
    return max(0.0, min(1.0, float(x)))

def percentile_rank(history, value):
    s = pd.Series(history).dropna()
    if s.empty:
        return 0.5
    return float((s <= value).mean())

def rsi(series, period=14):
    s = pd.Series(series).dropna()
    if len(s) < period + 2:
        return 50.0
    d = s.diff()
    gains = d.clip(lower=0)
    losses = -d.clip(upper=0)
    avg_gain = gains.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1/period, adjust=False).mean()
    loss = float(avg_loss.iloc[-1])
    gain = float(avg_gain.iloc[-1])
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    rs = gain / loss
    return 100.0 - (100.0 / (1.0 + rs))

for a in assets:
    symbol = a["yf"]
    try:
        ticker = yf.Ticker(symbol)

        # Get the latest tradable quote.
        latest = None
        try:
            fi = ticker.fast_info
            latest = fi.get("last_price") if hasattr(fi, "get") else fi["last_price"]
            if latest is not None:
                latest = float(latest)
        except Exception:
            latest = None

        # Three years gives enough history for cycle/trend context across all assets.
        hist = ticker.history(period="3y", interval="1d", auto_adjust=True)
        close = hist["Close"].dropna().astype(float)

        if close.empty:
            print(f"{symbol}: no price history")
            continue

        if latest is None:
            latest = float(close.iloc[-1])

        # Treat the current quote as today's latest close for risk calculation.
        calc = close.copy()
        if len(calc):
            calc.iloc[-1] = latest

        # 1) Long-term trend extension:
        # Compare price/200DMA to its own historical distribution.
        ma200 = calc.rolling(200, min_periods=120).mean()
        extension_series = (calc / ma200).replace([np.inf, -np.inf], np.nan).dropna()
        if len(extension_series):
            extension_now = float(extension_series.iloc[-1])
            trend_risk = percentile_rank(extension_series, extension_now)
        else:
            extension_now = 1.0
            trend_risk = 0.5

        # 2) Momentum via RSI14.
        rsi_now = rsi(calc, 14)
        momentum_risk = clamp01(rsi_now / 100.0)

        # 3) Relative price position within the 3-year history.
        price_position_risk = percentile_rank(calc, latest)

        # 4) Proximity to 3-year high.
        high_3y = float(calc.max())
        high_proximity_risk = clamp01(latest / high_3y) if high_3y > 0 else 0.5

        risk = (
            0.35 * trend_risk +
            0.25 * momentum_risk +
            0.25 * price_position_risk +
            0.15 * high_proximity_risk
        )
        risk = round(clamp01(risk), 4)

        prices[symbol] = round(latest, 6)
        risks[symbol] = risk
        components[symbol] = {
            "trend_extension": round(clamp01(trend_risk), 4),
            "momentum_rsi": round(clamp01(momentum_risk), 4),
            "price_position": round(clamp01(price_position_risk), 4),
            "high_proximity": round(clamp01(high_proximity_risk), 4),
            "rsi14": round(float(rsi_now), 2),
            "price_vs_200dma": round(float(extension_now), 4)
        }

        print(f"{symbol}: price={latest:.4f} risk={risk:.4f}")

    except Exception as e:
        print(f"{symbol}: {e}")

Path("data.json").write_text(json.dumps({
    "updated": datetime.now(timezone.utc).isoformat(),
    "prices": prices,
    "risks": risks,
    "components": components
}, indent=2))
