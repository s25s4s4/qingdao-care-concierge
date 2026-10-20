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


if __name__ == "__main__":
    items = load_items()
    print(f"归档 {len(items)} 场")
    if items:
        print("最近 3 场:")
        for x in items[-3:]:
            print(" ", x["date"], x["lg"], x["home"], f'{x["hg"]}-{x["ag"]}', x["away"])
