"""赛前冻结 + 依据留痕 + 独立结算（FotMob 第二源）。
原则：开赛后不再修改快照；结算只用外部源比分，不用本系统自报比分。
"""
import hashlib
import json
from datetime import datetime

import crosscheck


def _hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def freeze(match, now=None):
    """开赛前冻结预测；已有快照绝不覆盖。返回 True 表示本次新建。"""
    if match.get("prediction_snapshot"):
        return False
    kickoff = str(match.get("time", ""))
    try:
        dt = datetime.strptime(f"{datetime.now().year}-{kickoff}", "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return False
    now = now or datetime.now()
    if dt <= now:
        return False  # 已开赛，不补冻结
    if not match.get("tip") or not match.get("odds"):
        return False
    evidence = {
        "odds": match.get("odds"),
        "odds_source": match.get("source_name", "500.com"),
        "method": match.get("prediction_method") or "odds_implied_probability",
        "intel_used": bool(match.get("evidence")),
        "intel_ids": [e.get("id") for e in (match.get("evidence") or []) if isinstance(e, dict)][:10],
    }
    snapshot = {
        "tip": match.get("tip"),
        "predicted_scores": match.get("predicted_scores"),
        "predicted_goals": match.get("predicted_goals"),
        "consensus_ratio": match.get("consensus_ratio"),
        "is_only_rq": bool(match.get("is_only_rq")),
        "rang": match.get("rang", "0"),
        "frozen_at": now.isoformat(timespec="seconds"),
        "kickoff": dt.isoformat(timespec="seconds"),
        "evidence": evidence,
    }
    snapshot["sha256"] = _hash(snapshot)
    match["prediction_snapshot"] = snapshot
    match["prediction_verified"] = True
    match["provenance"] = {"method": evidence["method"], "evidence": "已留痕", "traceable": True,
                           "note": "赛前冻结，含赔率与生成方式哈希"}
    return True


def _score(value):
    try:
        a, b = str(value).replace(" ", "").split("-")
        return int(a), int(b)
    except (ValueError, AttributeError):
        return None


def settle(match, remote):
    """用外部源比分结算冻结预测。返回 'HIT'/'MISS'/'VOID'/None。"""
    snapshot = match.get("prediction_snapshot") or {}
    if not snapshot.get("frozen_at"):
        return None
    if not remote or not remote.get("finished"):
        return None
    parsed = _score(remote.get("score"))
    if not parsed:
        return None
    home, away = parsed
    tip = str(snapshot.get("tip") or "")
    if snapshot.get("is_only_rq"):
        try:
            rang = int(str(snapshot.get("rang", "0")).replace("+", ""))
        except ValueError:
            return None
        diff = home + rang - away
        outcome = "让胜" if diff > 0 else "让平" if diff == 0 else "让负"
    else:
        diff = home - away
        outcome = "主胜" if diff > 0 else "平局" if diff == 0 else "客胜"
    if "主不败" in tip:
        hit = outcome in ("主胜", "平局")
    elif "客不败" in tip:
        hit = outcome in ("客胜", "平局")
    elif "让" in tip:
        hit = outcome in ("让胜", "让平") if "让胜" in tip and "让平" in tip else outcome in tip
    else:
        hit = outcome in tip
    match["settlement"] = {"result": "HIT" if hit else "MISS", "score": remote.get("score"),
                           "source": "fotmob", "settled_at": datetime.now().isoformat(timespec="seconds"),
                           "outcome": outcome}
    match["result"] = match["settlement"]["result"]
    return match["result"]


def settle_all(matches):
    days = sorted({str(m.get("time", ""))[:5] for m in matches if m.get("time")})
    cache = {}
    for day in days:
        try:
            cache[day] = crosscheck.fetch_results("2026-" + day)
        except Exception:
            continue
    aliases = crosscheck._aliases()
    stats = {"hit": 0, "miss": 0, "skipped": 0}
    for m in matches:
        snapshot = m.get("prediction_snapshot") or {}
        if not snapshot.get("frozen_at"):
            stats["skipped"] += 1
            continue
        home = aliases.get(m.get("home"), m.get("home"))
        away = aliases.get(m.get("away"), m.get("away"))
        remote = None
        for day in (str(m.get("time", ""))[:5], crosscheck._prev(str(m.get("time", ""))[:5]) if hasattr(crosscheck, "_prev") else None):
            if day and cache.get(day):
                remote = cache[day].get((crosscheck._norm(home), crosscheck._norm(away)))
                if remote:
                    break
        outcome = settle(m, remote)
        if outcome == "HIT":
            stats["hit"] += 1
        elif outcome == "MISS":
            stats["miss"] += 1
        else:
            stats["skipped"] += 1
    return stats
