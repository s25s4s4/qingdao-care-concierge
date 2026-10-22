# -*- coding: utf-8 -*-
"""用 git 历史回填「赛前预测快照」，让历史场次进入可审计账本。

为什么这样算可信
----------------
仓库每几分钟自动提交一次 data/official_matches.json。对每场已完赛的比赛，
都能找到 kickoff 之前最后一次包含该文件的提交；如果那个版本里这场比赛
已经写着 tip / 预测比分 / 赔率，就说明这份预测在开赛前就真实存在。

回填出来的快照直接取自那个 commit 的内容（记录 commit sha + 时间 + 内容哈希），
任何人用 `git show <sha>:data/official_matches.json` 都能复核 —— 不是拿现在的
结果反推一个"看起来对"的预测。

必须守住的边界
--------------
1. 找不到 kickoff 之前的提交 → 不回填（标记 unbackfillable）
2. kickoff 之前有提交，但当时还没有 tip → 不回填
3. 回填快照一律带 origin='git_replay' / backfilled=True，与实时
   freeze() 产生的 'pre_match_freeze' 明确区分，统计时可分开看
"""
import json
import os
import subprocess
from datetime import datetime

import crosscheck
import verify

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data", "official_matches.json")
REL = "data/official_matches.json"
YEAR = datetime.now().year

_blob_cache = {}


CREATE_NO_WINDOW = 0x08000000


def _git(*args):
    return subprocess.run(["git", "-C", BASE] + list(args),
                          stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, encoding="utf-8",
                          creationflags=CREATE_NO_WINDOW)


def _commit_before(kickoff):
    r = _git("log", "-1", "--format=%H|%cI",
             "--before=" + kickoff.strftime("%Y-%m-%d %H:%M:%S"), "--", REL)
    out = (r.stdout or "").strip()
    if not out or "|" not in out:
        return None, None
    sha, when = out.split("|", 1)
    try:
        dt = datetime.fromisoformat(when.strip())
    except ValueError:
        return None, None
    return sha, dt


def _blob(sha):
    if sha in _blob_cache:
        return _blob_cache[sha]
    r = _git("show", "%s:%s" % (sha, REL))
    try:
        payload = json.loads(r.stdout)
    except Exception:
        payload = None
    _blob_cache[sha] = payload
    return payload


def _find(payload, match):
    if not payload:
        return None
    for x in payload.get("matches", []):
        if x.get("code") == match.get("code") and x.get("home") == match.get("home"):
            return x
    return None


def _prev_day(day):
    """'10-17' -> '10-16'（北京时间凌晨开球对应欧洲前一天）"""
    try:
        dt = datetime.strptime(str(YEAR) + "-" + day, "%Y-%m-%d")
        return (dt.fromordinal(dt.toordinal() - 1)).strftime("%m-%d")
    except ValueError:
        return None


def build_remote_map(matches):
    """按天抓 FotMob 结果，供独立结算使用。"""
    days = sorted({str(m.get("time", ""))[:5] for m in matches if m.get("time")})
    wanted = set(days)
    for d in days:
        prev = _prev_day(d)
        if prev:
            wanted.add(prev)
    out = {}
    for d in sorted(wanted):
        try:
            out[d] = crosscheck.fetch_results("%d-%s" % (YEAR, d))
        except Exception:
            continue
    return out


def backfill(matches, remote_map=None):
    """就地回填 matches 中缺失快照的已完赛场次。返回统计。"""
    aliases = crosscheck._aliases()
    # 只对「已完赛 + 没快照」的场次做网络请求，避免每次同步都去拉全量日期
    candidates = [m for m in matches
                  if not m.get("prediction_snapshot") and m.get("result") in ("HIT", "MISS")
                  and not m.get("backfill_blocked")]
    if remote_map is None:
        remote_map = build_remote_map(candidates) if candidates else {}

    stats = {"backfilled": 0, "already": 0, "no_commit": 0, "no_tip": 0,
             "not_found": 0, "skipped": 0}
    details = []

    for m in matches:
        if m.get("prediction_snapshot"):
            stats["already"] += 1
            continue
        if m.get("result") not in ("HIT", "MISS"):
            stats["skipped"] += 1
            continue
        try:
            kickoff = datetime.strptime("%d-%s" % (YEAR, m["time"]), "%Y-%m-%d %H:%M")
        except (KeyError, ValueError):
            stats["skipped"] += 1
            continue

        sha, commit_time = _commit_before(kickoff)
        if not sha:
            stats["no_commit"] += 1
            m["backfill_blocked"] = "no_pre_kickoff_commit"   # 标记后不再重复查 git
            details.append((m, "无赛前提交"))
            continue

        hist = _find(_blob(sha), m)
        if not hist:
            stats["not_found"] += 1
            details.append((m, "赛前提交里没有该场"))
            continue
        if not hist.get("tip"):
            stats["no_tip"] += 1
            details.append((m, "赛前提交里尚无 tip"))
            continue

        snapshot = {
            "tip": hist.get("tip"),
            "predicted_scores": hist.get("predicted_scores"),
            "predicted_goals": hist.get("predicted_goals"),
            "consensus_ratio": hist.get("consensus_ratio"),
            "is_only_rq": bool(hist.get("is_only_rq")),
            "rang": hist.get("rang", "0"),
            "frozen_at": commit_time.isoformat(timespec="seconds"),
            "kickoff": kickoff.isoformat(timespec="seconds"),
            "origin": "git_replay",
            "backfilled": True,
            "evidence": {
                "odds": hist.get("odds"),
                "odds_source": hist.get("source_name", "500.com"),
                "method": "git_replay",
                "git_commit": sha,
                "git_commit_time": commit_time.isoformat(timespec="seconds"),
                "git_path": REL,
                "note": "取自 kickoff 前最后一次提交，可用 git show 复核",
            },
        }
        snapshot["sha256"] = verify._hash(snapshot)
        m["prediction_snapshot"] = snapshot
        m["prediction_verified"] = True
        m["provenance"] = {
            "method": "git_replay",
            "evidence": "git 赛前提交留痕",
            "traceable": True,
            "note": "历史回填：预测取自开赛前最后一次提交，内容与 commit 均可复核",
        }

        # 独立结算：优先 FotMob，取不到才退回本地已记录的官方比分
        home = aliases.get(m.get("home"), m.get("home"))
        away = aliases.get(m.get("away"), m.get("away"))
        day = str(m.get("time", ""))[:5]
        remote = None
        for cand in (day, _prev_day(day)):
            if cand and remote_map.get(cand):
                remote = remote_map[cand].get((crosscheck._norm(home), crosscheck._norm(away)))
                if remote:
                    break
        outcome = verify.settle(m, remote)
        if outcome is None:
            outcome = verify.settle(m, {"finished": True, "score": m.get("score")})
            if m.get("settlement"):
                m["settlement"]["source"] = "stored_score"
        stats["backfilled"] += 1
        details.append((m, "回填 %s -> %s" % (snapshot["tip"], outcome)))

    return stats, details


def main():
    data = json.load(open(DATA, encoding="utf-8"))
    stats, details = backfill(data["matches"])

    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["total"] = len(data["matches"])
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("=== 回填结果 ===")
    for k, v in stats.items():
        print("  %-12s %d" % (k, v))
    print("\n=== 明细（前 30 条）===")
    for m, note in details[:30]:
        print("  %-8s %-10s vs %-10s %-6s %s" % (
            m.get("code"), m.get("home"), m.get("away"), m.get("result"), note))
    return stats


if __name__ == "__main__":
    main()
