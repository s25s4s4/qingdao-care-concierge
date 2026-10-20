# -*- coding: utf-8 -*-
"""把本地 14 年竞彩库算出的球队数据，合并进 official_matches.json。

设计原则：
  * 只补不覆盖 —— 已有 match["stats"] 就跳过，避免每分钟重复计算；
  * 全程 try/except —— 这一步失败绝不能让同步流水线中断；
  * 索引按文件 mtime 缓存 —— 一分钟跑一次不会反复读 8 万行 CSV。
"""
import os
import time
from datetime import datetime, timedelta

import team_stats as TS

_CACHE = {"mtime": None, "idx": None}


def full_date(t, today=None):
    """站点里的 time 是 'MM-DD HH:MM'（无年份），补成 YYYY-MM-DD。
    若补出来的日期比今天早 200 天以上，判定为跨年（去年 12 月 vs 今年 1 月）。"""
    if not t:
        return None
    today = today or datetime.now()
    try:
        md = t.strip()[:5]                      # 'MM-DD'
        dt = datetime.strptime(f"{today.year}-{md}", "%Y-%m-%d")
    except Exception:
        return None
    if (today - dt).days > 200:
        dt = dt.replace(year=dt.year + 1)
    return dt.strftime("%Y-%m-%d")


def _index():
    try:
        mt = os.path.getmtime(TS.CSV)
    except OSError:
        return None
    if _CACHE["idx"] is None or _CACHE["mtime"] != mt:
        _CACHE["idx"] = TS.load()
        _CACHE["mtime"] = mt
    return _CACHE["idx"]


def enrich(matches, limit=120, refresh_hours=12):
    """就地给 matches 补 stats，返回补充/刷新的场次数。
    已有 stats 的场次不是永久跳过：超过 refresh_hours 会重算，否则归档进来的新赛果永远进不去。"""
    idx = _index()
    if not idx:
        return 0
    now = datetime.now()
    n = 0
    for m in matches:
        if n >= limit:
            break
        if m.get("stats"):
            ts = m.get("stats_ts")
            fresh = False
            if ts:
                try:
                    fresh = (now - datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")).total_seconds() < refresh_hours * 3600
                except Exception:
                    fresh = False
            if fresh:
                continue
        home, away = m.get("home"), m.get("away")
        day = full_date(m.get("time"))
        if not home or not away or not day:
            continue
        try:
            blk = TS.build(home, away, day, idx)
        except Exception:
            continue
        if not (blk.get("home") or blk.get("away")):
            continue
        # 当季数据（Understat，仅五大联赛）：场次少但新鲜，且带 xG
        try:
            import fetch_understat as _us
            _d = _us.load()
            _lg = m.get("league")
            if _d and _lg in _d.get("leagues", {}):
                _h = _us.team_season(home, _lg, _d)
                _a = _us.team_season(away, _lg, _d)
                if _h or _a:
                    blk["season"] = {"home": _h, "away": _a,
                                     "updated_at": _d.get("updated_at"),
                                     "season": _d.get("season")}
        except Exception:
            pass
        m["stats"] = blk
        m["stats_ts"] = now.strftime("%Y-%m-%d %H:%M:%S")
        n += 1
    return n


if __name__ == "__main__":
    import json
    import sys

    _args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    path = _args[0] if _args else r"E:\euro_intel_web\data\official_matches.json"
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    ms = d.get("matches") or []
    k = enrich(ms, refresh_hours=0 if force else 12)
    if k:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    print(f"补充 {k} 场 / 共 {len(ms)} 场 -> {path}")
