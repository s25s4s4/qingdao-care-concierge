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
    """用外部源比分结算预测。返回 'HIT'/'MISS'/'VOID'/None。"""
    if not remote or not remote.get("finished"):
        return None
    parsed = _score(remote.get("score"))
    if not parsed:
        return None
    home, away = parsed

    # 优先采用 match 当时展示给彩民的核心建议 tip，若无再回落 snapshot
    tip = str(match.get("tip") or (match.get("prediction_snapshot") or {}).get("tip") or "")
    if not tip:
        return None

    rang_val = None
    if match.get("rang") is not None and str(match.get("rang")) not in ("None", "0", ""):
        try:
            rang_val = int(str(match.get("rang")).replace("+", ""))
        except ValueError:
            rang_val = None

    diff = home - away
    spf_outcome = "主胜" if diff > 0 else "平局" if diff == 0 else "客胜"
    
    if rang_val is not None:
        rq_diff = (home + rang_val) - away
        rq_outcome = "让胜" if rq_diff > 0 else "让平" if rq_diff == 0 else "让负"
    else:
        # 无让球盘口时，让负视同客不败(客胜或平局)
        rq_outcome = "客不败" if diff <= 0 else "主胜"

    hit = False
    if "让负/防让平" in tip or ("让负" in tip and "让平" in tip):
        hit = (rq_outcome in ("让负", "让平"))
    elif "让胜/防让平" in tip or ("让胜" in tip and "让平" in tip):
        hit = (rq_outcome in ("让胜", "让平"))
    elif "让负" in tip:
        if rang_val is not None:
            hit = (rq_outcome == "让负")
        else:
            hit = (diff <= 0) # 无让球盘时买让负等同客不败(平局或客胜)
    elif "让胜" in tip:
        if rang_val is not None:
            hit = (rq_outcome == "让胜")
        else:
            hit = (diff >= 0)
    elif "让平" in tip:
        hit = (rq_outcome == "让平")
    elif "主不败" in tip or "主胜/防平" in tip or "胜平" in tip:
        hit = (spf_outcome in ("主胜", "平局"))
    elif "客不败" in tip or "客胜/防平" in tip or "平负" in tip:
        hit = (spf_outcome in ("客胜", "平局"))
    elif "主胜" in tip:
        hit = (spf_outcome == "主胜")
    elif "客胜" in tip:
        hit = (spf_outcome == "客胜")
    elif "平局" in tip or "平" in tip:
        hit = (spf_outcome == "平局")
    else:
        hit = (spf_outcome in tip or rq_outcome in tip)

    outcome = rq_outcome if "让" in tip else spf_outcome
    match["settlement"] = {"result": "HIT" if hit else "MISS", "score": remote.get("score"),
                           "source": remote.get("source", "stored_score"), "settled_at": datetime.now().isoformat(timespec="seconds"),
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
        if outcome is None:
            # 只有当比赛明确为【已完赛】且有真实终场比分时，才允许退回 stored_score 结算！
            # 绝不能对【正在进行中 (is_live / PENDING)】的半场 0-0 误判为完赛！
            if m.get("status") == "已完赛" and m.get("result") != "PENDING" and m.get("score") and m.get("score") not in ("--", "延期"):
                outcome = settle(m, {"finished": True, "score": m.get("score")})
                if outcome and m.get("settlement"):
                    m["settlement"]["source"] = "stored_score"
        if outcome == "HIT":
            stats["hit"] += 1
        elif outcome == "MISS":
            stats["miss"] += 1
        else:
            stats["skipped"] += 1
    return stats


def freeze_mid(match, now=None):
    """比赛已开赛但仍在进行：立即冻结当前建议，防止赛后改动；明确标记非赛前。"""
    if match.get("prediction_snapshot"):
        return False
    if not match.get("tip"):
        return False
    now = now or datetime.now()
    snapshot = {
        "tip": match.get("tip"),
        "predicted_scores": match.get("predicted_scores"),
        "predicted_goals": match.get("predicted_goals"),
        "consensus_ratio": match.get("consensus_ratio"),
        "is_only_rq": bool(match.get("is_only_rq")),
        "rang": match.get("rang", "0"),
        "frozen_at": now.isoformat(timespec="seconds"),
        "kickoff": str(match.get("time")),
        "frozen_mid_match": True,
        "verified_pre_match": False,
        "evidence": {"odds": match.get("odds"), "odds_source": match.get("source_name", "500.com"),
                     "method": "frozen_after_kickoff"},
    }
    snapshot["sha256"] = _hash(snapshot)
    match["prediction_snapshot"] = snapshot
    match["provenance"] = {"method": "frozen_after_kickoff", "evidence": "开赛中冻结", "traceable": True,
                           "note": "开赛后冻结，仅防止赛后改动，不作为赛前能力证明"}
    match["prediction_verified"] = False
    return True
