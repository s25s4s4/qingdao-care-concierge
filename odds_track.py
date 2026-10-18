"""赔率轨迹记录 + CLV + 回测。
赔率历史是后续所有改进（模型校准、价值投注、CLV）的基础数据。
"""
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
HISTORY = os.path.join(BASE, "data", "odds_history.jsonl")


def _key(m):
    return "%s|%s|%s|%s" % (m.get("time"), m.get("home"), m.get("away"), m.get("league"))


def record(matches, now=None):
    """每次同步记录一次赔率快照；仅当赔率变化时追加，避免刷屏。"""
    now = now or datetime.now()
    stamp = now.isoformat(timespec="seconds")
    last = {}
    try:
        with open(HISTORY, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    last[row["k"]] = row["odds"]
                except (ValueError, KeyError):
                    continue
    except OSError:
        pass
    added = 0
    with open(HISTORY, "a", encoding="utf-8") as f:
        for m in matches:
            odds = m.get("odds")
            if not (isinstance(odds, list) and len(odds) == 3):
                continue
            k = _key(m)
            if last.get(k) == odds:
                continue
            f.write(json.dumps({"k": k, "code": m.get("code"), "odds": odds, "ts": stamp,
                                "kickoff": m.get("time"), "source": m.get("source_name", "500.com")},
                               ensure_ascii=False) + "\n")
            added += 1
    return added


def history_for(match):
    k = _key(match)
    rows = []
    try:
        with open(HISTORY, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("k") == k:
                    rows.append(row)
    except OSError:
        return []
    return rows


def closing_odds(match):
    """收盘赔率 = 开赛前最后一条记录。"""
    rows = history_for(match)
    if not rows:
        return None
    kickoff = str(match.get("time", ""))
    pre = [r for r in rows if str(r.get("ts", ""))[:16] < "2026-" + kickoff[:10] + " " + kickoff[11:16]]
    return (pre or rows)[-1]


def clv(match, snapshot=None):
    """CLV：冻结时赔率 vs 收盘赔率。正值代表拿到比收盘更好的价格。"""
    snapshot = snapshot or (match.get("prediction_snapshot") or {})
    frozen = (snapshot.get("evidence") or {}).get("odds")
    close = closing_odds(match)
    if not frozen or not close:
        return None
    tip = str(snapshot.get("tip") or "")
    idx = 0 if "主" in tip else 2 if "客" in tip else 1
    try:
        f, c = float(frozen[idx]), float(close["odds"][idx])
    except (ValueError, IndexError, TypeError):
        return None
    if c <= 1:
        return None
    return round((f / c - 1) * 100, 2)


def backtest(matches):
    """walk-forward 回测：只用已结算且有冻结快照的比赛。"""
    settled = [m for m in matches if (m.get("settlement") or {}).get("result") in ("HIT", "MISS")
               and (m.get("prediction_snapshot") or {}).get("frozen_at")]
    if not settled:
        return {"samples": 0}
    hits = sum(1 for m in settled if m["settlement"]["result"] == "HIT")
    stake = payout = 0.0
    briers = []
    for m in settled:
        snap = m["prediction_snapshot"]
        odds = (snap.get("evidence") or {}).get("odds") or []
        tip = str(snap.get("tip") or "")
        idx = 0 if "主" in tip else 2 if "客" in tip else 1
        try:
            sp = float(odds[idx])
        except (ValueError, IndexError, TypeError):
            continue
        stake += 1
        if m["settlement"]["result"] == "HIT":
            payout += sp
        p = (snap.get("consensus_ratio") or 50) / 100
        y = 1 if m["settlement"]["result"] == "HIT" else 0
        briers.append((p - y) ** 2)
    clvs = [c for c in (clv(m) for m in settled) if c is not None]
    return {
        "samples": len(settled),
        "hit_rate": round(hits / len(settled) * 100, 2),
        "roi": round((payout - stake) / stake * 100, 2) if stake else None,
        "brier": round(sum(briers) / len(briers), 4) if briers else None,
        "clv_avg": round(sum(clvs) / len(clvs), 2) if clvs else None,
        "clv_samples": len(clvs),
    }
