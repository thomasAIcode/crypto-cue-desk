import sys
import json
import argparse
import urllib.request
import ccxt
import numpy as np
import pandas as pd
from db_manager import (
    open_paper_trade,
    close_paper_trade,
    record_prediction,
    validate_prediction,
    get_portfolio_summary,
)

def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "CueCryptoDesk/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))

def get_market_snapshot(symbol: str = "BTC/USDT"):
    """Tích hợp crypto-exchange, crypto-data, crypto-futures, DefiLlama & Polymarket"""
    exchange = ccxt.binance({"enableRateLimit": True})
    ticker = exchange.fetch_ticker(symbol)
    orderbook = exchange.fetch_order_book(symbol, limit=20)
    
    bid_vol = sum([b[1] for b in orderbook["bids"]])
    ask_vol = sum([a[1] for a in orderbook["asks"]])
    imbalance = round((bid_vol - ask_vol) / (bid_vol + ask_vol + 1e-9), 4)
    spread_bps = round(((orderbook["asks"][0][0] - orderbook["bids"][0][0]) / ticker["last"]) * 10000, 2)

    try:
        fng = fetch_json("https://api.alternative.me/fng/?limit=1")["data"][0]
    except Exception:
        fng = {"value": "N/A", "value_classification": "N/A"}

    try:
        chains = fetch_json("https://api.llama.fi/v2/chains")
        total_tvl = sum(c.get("tvl", 0) for c in chains)
    except Exception:
        total_tvl = 0

    return {
        "symbol": symbol,
        "price": ticker["last"],
        "change_24h_pct": ticker["percentage"],
        "volume_24h_usdt": ticker["quoteVolume"],
        "microstructure": {
            "orderbook_imbalance": imbalance,
            "spread_bps": spread_bps,
            "signal": "BULLISH_DEPTH" if imbalance > 0.2 else ("BEARISH_DEPTH" if imbalance < -0.2 else "NEUTRAL")
        },
        "macro_sentiment": {
            "fear_and_greed_value": fng.get("value"),
            "fear_and_greed_label": fng.get("value_classification"),
            "defi_global_tvl_billion": round(total_tvl / 1e9, 2)
        }
    }

def get_technical_analysis(symbol: str = "BTC/USDT", timeframe: str = "4h"):
    """Tích hợp crypto-technical & crypto-advanced-indicators"""
    exchange = ccxt.binance({"enableRateLimit": True})
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "vol"])
    
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    df["rsi"] = 100 - (100 / (1 + rs))
    
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    
    sma20 = df["close"].rolling(window=20).mean()
    std20 = df["close"].rolling(window=20).std()
    upper_bb = sma20 + 2 * std20
    lower_bb = sma20 - 2 * std20

    high_low = df["high"] - df["low"]
    atr = high_low.rolling(window=14).mean().iloc[-1]

    last = df.iloc[-1]
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "close": float(last["close"]),
        "rsi_14": round(float(last["rsi"]), 2),
        "macd_hist": round(float(last["macd"] - last["signal"]), 4),
        "bb_upper": round(float(upper_bb.iloc[-1]), 2),
        "bb_lower": round(float(lower_bb.iloc[-1]), 2),
        "atr_14": round(float(atr), 2),
        "suggested_sl_long": round(float(last["close"] - 2.0 * atr), 2),
        "suggested_tp_long": round(float(last["close"] + 4.5 * atr), 2)
    }

def check_sl_tp():
    """Tự động kiểm tra các lệnh đang mở xem đã chạm Stop-Loss hay Take-Profit chưa"""
    summary = get_portfolio_summary()
    open_trades = summary.get("open_trades", [])
    exchange = ccxt.binance({"enableRateLimit": True})
    alerts = []

    for t in open_trades:
        sym = t["symbol"]
        ticker = exchange.fetch_ticker(sym)
        price = float(ticker["last"])
        side = t["side"]
        sl = float(t["stop_loss"])
        tp = float(t["take_profit"])

        if side == "LONG":
            if price <= sl:
                res = close_paper_trade(t["trade_id"], price, f"Auto-closed: Hit Stop-Loss at {price}")
                alerts.append({"event": "STOP_LOSS_HIT", "price": price, "result": res})
            elif price >= tp:
                res = close_paper_trade(t["trade_id"], price, f"Auto-closed: Hit Take-Profit at {price}")
                alerts.append({"event": "TAKE_PROFIT_HIT", "price": price, "result": res})
        elif side == "SHORT":
            if price >= sl:
                res = close_paper_trade(t["trade_id"], price, f"Auto-closed: Hit Stop-Loss at {price}")
                alerts.append({"event": "STOP_LOSS_HIT", "price": price, "result": res})
            elif price <= tp:
                res = close_paper_trade(t["trade_id"], price, f"Auto-closed: Hit Take-Profit at {price}")
                alerts.append({"event": "TAKE_PROFIT_HIT", "price": price, "result": res})

    return {"checked_trades": len(open_trades), "triggered_events": alerts}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cue Crypto Desk Toolkit")
    sub = parser.add_subparsers(dest="cmd")

    p_snap = sub.add_parser("snapshot")
    p_snap.add_argument("--symbol", default="BTC/USDT")

    p_ta = sub.add_parser("ta")
    p_ta.add_argument("--symbol", default="BTC/USDT")
    p_ta.add_argument("--tf", default="4h")

    p_trade = sub.add_parser("open-trade")
    p_trade.add_argument("--symbol", required=True)
    p_trade.add_argument("--side", required=True)
    p_trade.add_argument("--entry", type=float, required=True)
    p_trade.add_argument("--sl", type=float, required=True)
    p_trade.add_argument("--tp", type=float, required=True)
    p_trade.add_argument("--size", type=float, default=1000.0)
    p_trade.add_argument("--pattern", required=True)

    p_close = sub.add_parser("close-trade")
    p_close.add_argument("--id", required=True)
    p_close.add_argument("--exit", type=float, required=True)
    p_close.add_argument("--notes", required=True)

    p_pred = sub.add_parser("add-prediction")
    p_pred.add_argument("--trade-id", default="N/A")
    p_pred.add_argument("--agent", required=True)
    p_pred.add_argument("--symbol", required=True)
    p_pred.add_argument("--text", required=True)
    p_pred.add_argument("--metric", required=True)
    p_pred.add_argument("--hours", type=int, default=24)

    p_val = sub.add_parser("validate-prediction")
    p_val.add_argument("--id", type=int, required=True)
    p_val.add_argument("--accurate", type=int, choices=[0, 1], required=True)
    p_val.add_argument("--outcome", required=True)

    sub.add_parser("portfolio")
    sub.add_parser("monitor")

    args = parser.parse_args()
    if args.cmd == "snapshot":
        print(json.dumps(get_market_snapshot(args.symbol), indent=2))
    elif args.cmd == "ta":
        print(json.dumps(get_technical_analysis(args.symbol, args.tf), indent=2))
    elif args.cmd == "open-trade":
        print(json.dumps(open_paper_trade(args.symbol, args.side, args.entry, args.sl, args.tp, args.size, args.pattern), indent=2))
    elif args.cmd == "close-trade":
        print(json.dumps(close_paper_trade(args.id, args.exit, args.notes), indent=2))
    elif args.cmd == "add-prediction":
        print(json.dumps(record_prediction(args.trade_id, args.agent, args.symbol, args.text, args.metric, args.hours), indent=2))
    elif args.cmd == "validate-prediction":
        print(json.dumps(validate_prediction(args.id, args.accurate, args.outcome), indent=2))
    elif args.cmd == "portfolio":
        print(json.dumps(get_portfolio_summary(), indent=2))
    elif args.cmd == "monitor":
        print(json.dumps(check_sl_tp(), indent=2))
