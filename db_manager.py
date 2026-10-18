import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "db" / "learning.db"

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Bảng quản lý danh mục & lệnh Paper Trading
    c.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        trade_id TEXT PRIMARY KEY,
        symbol TEXT,
        side TEXT,
        entry_price REAL,
        stop_loss REAL,
        take_profit REAL,
        size_usd REAL,
        setup_pattern TEXT,
        status TEXT DEFAULT 'OPEN',
        exit_price REAL,
        pnl_usd REAL,
        opened_at TEXT,
        closed_at TEXT,
        post_mortem_nl TEXT
    )""")

    # Bảng theo dõi dự đoán của các Agent (Cognitive Learning)
    c.execute("""
    CREATE TABLE IF NOT EXISTS predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id TEXT,
        agent_name TEXT,
        symbol TEXT,
        prediction_text TEXT,
        target_metric TEXT,
        timeframe_hours INTEGER,
        created_at TEXT,
        validated INTEGER DEFAULT 0,
        outcome_nl TEXT,
        is_accurate INTEGER
    )""")

    # Bảng thư viện mẫu hình (Pattern Library: SEEK >= 60%, AVOID <= 40%)
    c.execute("""
    CREATE TABLE IF NOT EXISTS patterns (
        pattern_name TEXT PRIMARY KEY,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        win_rate REAL DEFAULT 0.0,
        classification TEXT DEFAULT 'NEUTRAL',
        notes TEXT
    )""")
    conn.commit()
    conn.close()

def open_paper_trade(symbol: str, side: str, entry: float, sl: float, tp: float, size_usd: float, pattern: str):
    init_db()
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    if risk == 0 or (reward / risk) < 2.0:
        return {"error": f"Vi phạm nguyên tắc rủi ro: Tỷ lệ R:R ({reward/(risk+1e-9):.2f}) nhỏ hơn mức tối thiểu 2.0"}

    trade_id = f"trade_{int(datetime.utcnow().timestamp())}"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO trades (trade_id, symbol, side, entry_price, stop_loss, take_profit, size_usd, setup_pattern, opened_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (trade_id, symbol.upper(), side.upper(), entry, sl, tp, size_usd, pattern, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()
    return {"status": "EXECUTED", "trade_id": trade_id, "r_r_ratio": round(reward / risk, 2)}

def close_paper_trade(trade_id: str, exit_price: float, post_mortem: str):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    trade = c.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,)).fetchone()
    if not trade or trade["status"] != "OPEN":
        return {"error": "Không tìm thấy lệnh đang mở."}

    direction = 1 if trade["side"] == "LONG" else -1
    pnl_pct = ((exit_price - trade["entry_price"]) / trade["entry_price"]) * direction
    pnl_usd = round(trade["size_usd"] * pnl_pct, 2)

    c.execute("""
        UPDATE trades SET status = 'CLOSED', exit_price = ?, pnl_usd = ?, closed_at = ?, post_mortem_nl = ?
        WHERE trade_id = ?
    """, (exit_price, pnl_usd, datetime.utcnow().isoformat(), post_mortem, trade_id))

    pat = trade["setup_pattern"]
    is_win = 1 if pnl_usd > 0 else 0
    row = c.execute("SELECT * FROM patterns WHERE pattern_name = ?", (pat,)).fetchone()
    wins = (row["wins"] if row else 0) + is_win
    losses = (row["losses"] if row else 0) + (0 if is_win else 1)
    total = wins + losses
    win_rate = round((wins / total) * 100, 2)
    classification = "SEEK" if win_rate >= 60 else ("AVOID" if win_rate <= 40 and total >= 3 else "NEUTRAL")

    c.execute("""
        INSERT INTO patterns (pattern_name, wins, losses, win_rate, classification, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(pattern_name) DO UPDATE SET
        wins=?, losses=?, win_rate=?, classification=?, notes=?
    """, (pat, wins, losses, win_rate, classification, post_mortem, wins, losses, win_rate, classification, post_mortem))

    conn.commit()
    conn.close()
    return {"trade_id": trade_id, "pnl_usd": pnl_usd, "pattern": pat, "pattern_status": classification}

def record_prediction(trade_id: str, agent_name: str, symbol: str, prediction_text: str, target_metric: str, timeframe_hours: int):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO predictions (trade_id, agent_name, symbol, prediction_text, target_metric, timeframe_hours, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (trade_id, agent_name, symbol.upper(), prediction_text, target_metric, timeframe_hours, datetime.utcnow().isoformat()))
    pred_id = c.lastrowid
    conn.commit()
    conn.close()
    return {"status": "RECORDED", "prediction_id": pred_id}

def validate_prediction(pred_id: int, is_accurate: int, outcome_nl: str):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE predictions SET validated = 1, is_accurate = ?, outcome_nl = ?
        WHERE id = ?
    """, (is_accurate, outcome_nl, pred_id))
    conn.commit()
    conn.close()
    return {"status": "VALIDATED", "prediction_id": pred_id, "is_accurate": bool(is_accurate)}

def get_portfolio_summary():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    open_trades = [dict(r) for r in c.execute("SELECT * FROM trades WHERE status = 'OPEN'").fetchall()]
    closed_pnl = c.execute("SELECT COALESCE(SUM(pnl_usd), 0) FROM trades WHERE status = 'CLOSED'").fetchone()[0]
    patterns = [dict(r) for r in c.execute("SELECT * FROM patterns").fetchall()]
    pending_preds = [dict(r) for r in c.execute("SELECT * FROM predictions WHERE validated = 0").fetchall()]
    conn.close()
    return {
        "initial_balance_usd": 20000.0,
        "realized_pnl_usd": round(closed_pnl, 2),
        "current_equity_usd": round(20000.0 + closed_pnl, 2),
        "open_trades": open_trades,
        "pattern_library": patterns,
        "pending_predictions": pending_preds
    }
