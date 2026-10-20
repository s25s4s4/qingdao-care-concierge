# -*- coding: utf-8 -*-
"""赛果归档：把每场完赛结果追加到 data/match_results.jsonl。

为什么单独存一份而不是回写桌面那份 14 年 CSV：
  * 桌面 CSV 是研究用的原始数据，流水线不应该去改它；
  * JSONL 追加写，不会因为并发/中断把整份文件写坏；
  * team_stats 读的时候两份合并，等价于"库一直在长"。

一行一条：
  {"code":"周二001","date":"2026-10-16","league":"澳超","home":"悉尼FC","away":"西悉尼",
   "hg":0,"ag":0,"res":"平","src":"live500"}
"""
import json
import os
from datetime import datetime

ARCHIVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "match_results.jsonl")
STATS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "archive_stats.json")


def _parse_score(s):
    if not s or "-" not in s:
        return None
    try:
        a, b = s.replace(":", "-").split("-")[:2]
        return int(a), int(b)
    except Exception:
        return None


def load_codes(path=ARCHIVE):
    """已归档的 code 集合，用于去重"""
    seen = set()
    if not os.path.exists(path):
        return seen
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    seen.add(json.loads(line).get("code"))
                except Exception:
                    continue
    except Exception:
        pass
    return seen


def append(matches, path=ARCHIVE, date_of=None):
    """matches: 已完成、且带 score 的比赛对象列表。返回新写入条数。"""
    if not matches:
        return 0
    seen = load_codes(path)
    rows = []
    for m in matches:
        code = m.get("code")
        if not code or code in seen:
            continue
        sc = _parse_score(m.get("score"))
        if not sc:
            continue
        day = date_of(m) if date_of else None
        if not day:
            continue
        hg, ag = sc
        rows.append({
            "code": code,
            "date": day,
            "league": m.get("league", ""),
            "home": m.get("home", ""),
            "away": m.get("away", ""),
            "hg": hg,
            "ag": ag,
            "res": "胜" if hg > ag else ("平" if hg == ag else "负"),
            "src": "live500",
        })
        seen.add(code)
    if not rows:
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


def load_items(path=ARCHIVE):
    """转成 team_stats 能直接吃的条目格式"""
    items = []
    if not os.path.exists(path):
        return items
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if not r.get("date") or not r.get("home"):
                    continue
                items.append({
                    "date": r["date"],
                    "lg": r.get("league", ""),
                    "home": r["home"],
                    "away": r["away"],
                    "hg": int(r.get("hg", 0)),
                    "ag": int(r.get("ag", 0)),
                    "res": r.get("res", ""),
                    "oh": None, "od": None, "oa": None,
                })
    except Exception:
        pass
    return items


def snapshot(path=ARCHIVE):
    """归档覆盖度快照：总数、球队数、联赛分布、能凑齐 10 场的球队数"""
    items = load_items(path)
    teams = {}
    leagues = {}
    for x in items:
        for t in (x["home"], x["away"]):
            teams[t] = teams.get(t, 0) + 1
        leagues[x["lg"]] = leagues.get(x["lg"], 0) + 1
    ready = sum(1 for c in teams.values() if c >= 10)
    return {
        "total": len(items),
        "teams": len(teams),
        "teams_ge10": ready,
        "leagues": len(leagues),
        "by_league": dict(sorted(leagues.items(), key=lambda kv: -kv[1])),
        "first_date": items[0]["date"] if items else None,
        "last_date": items[-1]["date"] if items else None,
    }


def record_stats(added=0, path=ARCHIVE, stats_path=STATS):
    """把今天的覆盖度写进 archive_stats.json（按日期 upsert，一天一行）"""
    snap = snapshot(path)
    day = datetime.now().strftime("%Y-%m-%d")
    data = {"days": []}
    if os.path.exists(stats_path):
        try:
            with open(stats_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"days": []}
    days = [d for d in data.get("days", []) if d.get("date") != day]
    days.append({
        "date": day,
        "total": snap["total"],
        "added": added,
        "teams": snap["teams"],
        "teams_ge10": snap["teams_ge10"],
        "leagues": snap["leagues"],
    })
    days.sort(key=lambda d: d["date"])
    data["days"] = days[-180:]          # 只留最近 180 天
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.dirname(stats_path), exist_ok=True)
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return snap


if __name__ == "__main__":
    import sys
    if "--stats" in sys.argv:
        snap = snapshot()
        print(f"归档总数 {snap['total']} 场  球队 {snap['teams']} 支  联赛 {snap['leagues']} 个")
        print(f"能凑齐 10 场的球队：{snap['teams_ge10']} 支 "
              f"({snap['teams_ge10'] / snap['teams'] * 100 if snap['teams'] else 0:.0f}%)")
        print(f"日期范围 {snap['first_date']} ~ {snap['last_date']}")
        print("\n联赛分布 Top10:")
        for lg, c in list(snap["by_league"].items())[:10]:
            print(f"  {lg:<12}{c:>5} 场")
        if os.path.exists(STATS):
            with open(STATS, encoding="utf-8") as f:
                days = json.load(f).get("days", [])
            print("\n每日归档:")
            print("  %-12s%8s%8s%8s%10s" % ("日期", "总数", "新增", "球队", "可凑10场"))
            for d in days[-14:]:
                print("  %-12s%8d%8d%8d%10d" % (d["date"], d["total"], d["added"], d["teams"], d["teams_ge10"]))
        raise SystemExit(0)

    items = load_items()
    print(f"归档 {len(items)} 场")
    if items:
        print("最近 3 场:")
        for x in items[-3:]:
            print(" ", x["date"], x["lg"], x["home"], f'{x["hg"]}-{x["ag"]}', x["away"])
