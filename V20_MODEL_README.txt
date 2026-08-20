Di4m0ndH4nd5 V20 Risk Model

V20 uses different weightings for:
- Crypto
- Stocks
- Indices
- Metals

Signals:
1. Volatility-normalised distance from the 200-day moving average
2. RSI(14) momentum
3. Drawdown from the 3-year high
4. Position within the 3-year price distribution
5. 30-day realised volatility relative to the asset's own history

Key improvement:
The same price move is no longer treated equally across Bitcoin, Coca-Cola, gold, indices, etc.
Trend distance is divided by each asset's recent volatility before being scored.

The model recalculates hourly whenever the GitHub Action runs.
