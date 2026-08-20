import json
from datetime import datetime, timezone
from pathlib import Path
import yfinance as yf

assets = json.loads(Path("assets.json").read_text())
prices = {}

for a in assets:
    symbol = a["yf"]
    price = None
    try:
        ticker = yf.Ticker(symbol)

        # Fastest/latest quote when Yahoo exposes it.
        try:
            fi = ticker.fast_info
            price = fi.get("last_price") if hasattr(fi, "get") else fi["last_price"]
        except Exception:
            price = None

        # Intraday fallback.
        if price is None:
            hist = ticker.history(period="1d", interval="1m", prepost=False)
            if not hist.empty:
                price = float(hist["Close"].dropna().iloc[-1])

        # Daily fallback for closed markets / instruments without minute data.
        if price is None:
            hist = ticker.history(period="5d", interval="1d")
            if not hist.empty:
                price = float(hist["Close"].dropna().iloc[-1])

        if price is not None:
            prices[symbol] = round(float(price), 6)

    except Exception as e:
        print(f"{symbol}: {e}")

Path("data.json").write_text(json.dumps({
    "updated": datetime.now(timezone.utc).isoformat(),
    "prices": prices
}, indent=2))
