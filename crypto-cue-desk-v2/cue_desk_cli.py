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

def detect_crt_ict_patterns(df: pd.DataFrame):
    """
    Phát hiện mẫu hình CRT (Candle Range Theory) và ICT (Inner Circle Trader)
    dựa trên hành vi nến (Candlestick Analysis):
    1. CRT: C1 thiết lập range, C2 quét qua High/Low nhưng rút râu đóng vào trong range (Close-Back-Inside).
    2. ICT FVG: Khoảng trống giá Fair Value Gap giữa Candle [i-2] và Candle [i].
    3. ICT Liquidity Sweep: Quét đỉnh/đáy 20 nến trước đó.
    """
    signals = []
    if len(df) < 5:
        return signals

    c1 = df.iloc[-3] # Anchor Candle (C1)
    c2 = df.iloc[-2] # Sweep Candle (C2)
    c3 = df.iloc[-1] # Current / Entry Candle (C3)

    # --- 1. CRT BULLISH SETUP ---
    # Điều kiện CRT Bullish: C2 chọc thủng đáy C1 (quét Sell-side Liquidity) nhưng giá đóng cửa C2 lại nằm TRÊN đáy C1
    if c2["low"] < c1["low"] and c2["close"] > c1["low"]:
        signals.append({
            "pattern": "crt_bullish_sweep_reentry",
            "type": "CRT",
            "direction": "LONG",
            "confidence": 80,
            "anchor_high": float(c1["high"]),
            "anchor_low": float(c1["low"]),
            "sweep_low": float(c2["low"]),
            "target_tp": float(c1["high"]),
            "suggested_sl": float(c2["low"] * 0.998),
            "description": "CRT Bullish: C2 quét thủng CRT-Low của C1 nhưng rút râu đóng nến bên trong range. Kỳ vọng giá chạy về CRT-High."
        })

    # --- 2. CRT BEARISH SETUP ---
    # Điều kiện CRT Bearish: C2 chọc thủng đỉnh C1 (quét Buy-side Liquidity) nhưng giá đóng cửa C2 lại nằm DƯỚI đỉnh C1
    if c2["high"] > c1["high"] and c2["close"] < c1["high"]:
        signals.append({
            "pattern": "crt_bearish_sweep_reentry",
            "type": "CRT",
            "direction": "SHORT",
            "confidence": 80,
            "anchor_high": float(c1["high"]),
            "anchor_low": float(c1["low"]),
            "sweep_high": float(c2["high"]),
            "target_tp": float(c1["low"]),
            "suggested_sl": float(c2["high"] * 1.002),
            "description": "CRT Bearish: C2 quét vượt CRT-High của C1 nhưng rút râu đóng nến bên trong range. Kỳ vọng giá hồi về CRT-Low."
        })

    # --- 3. ICT BULLISH FVG (Fair Value Gap) ---
    # C1 High < C3 Low (tạo khoảng trống giữa C1 và C3)
    if c1["high"] < c3["low"]:
        signals.append({
            "pattern": "ict_2022_mentorship_model",
            "type": "ICT",
            "direction": "LONG",
            "confidence": 75,
            "fvg_top": float(c3["low"]),
            "fvg_bottom": float(c1["high"]),
            "suggested_sl": float(c2["low"] * 0.997),
            "suggested_tp": float(c3["close"] + (c3["close"] - c2["low"]) * 2.2),
            "description": f"ICT Bullish FVG: Khoảng trống tăng giá giữa {c1['high']} và {c3['low']} tạo vùng cầu (Demand Imbalance)."
        })

    # --- 4. ICT BEARISH FVG ---
    # C1 Low > C3 High
    if c1["low"] > c3["high"]:
        signals.append({
            "pattern": "ict_2022_mentorship_model",
            "type": "ICT",
            "direction": "SHORT",
            "confidence": 75,
            "fvg_top": float(c1["low"]),
            "fvg_bottom": float(c3["high"]),
            "suggested_sl": float(c2["high"] * 1.003),
            "suggested_tp": float(c3["close"] - (c2["high"] - c3["close"]) * 2.2),
            "description": f"ICT Bearish FVG: Khoảng trống giảm giá giữa {c3['high']} và {c1['low']} tạo vùng cung (Supply Imbalance)."
        })

    return signals

def get_market_snapshot(symbol: str = "BTC/USDT"):
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
    exchange = ccxt.binance({"enableRateLimit": True})
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "vol"])
    
    # RSI (14)
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    df["rsi"] = 100 - (100 / (1 + rs))
    
    # MACD
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    
    # ATR
    high_low = df["high"] - df["low"]
    atr = high_low.rolling(window=14).mean().iloc[-1]

    last = df.iloc[-1]
    
    # Quét nhận diện tự động ICT & CRT Setups
    detected_setups = detect_crt_ict_patterns(df)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "close": float(last["close"]),
        "rsi_14": round(float(last["rsi"]), 2),
        "macd_hist": round(float(last["macd"] - last["signal"]), 4),
        "atr_14": round(float(atr), 2),
        "detected_crt_ict_setups": detected_setups
    }

def check_sl_tp():
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
    parser = argparse.ArgumentParser(description="Cue Crypto Desk Toolkit (ICT & CRT Enhanced)")
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
