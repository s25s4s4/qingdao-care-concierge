# -*- coding: utf-8 -*-
"""把本地 14 年竞彩库算出的球队数据与 Understat 五大联赛本季 xG 合并进 official_matches.json。

设计原则：
  * 绝不用旧 CSV 覆盖 live_team_form 刚抓到的新鲜 FotMob 近期战绩（按 last_date 择新保留）；
  * 即使已有 live_team_form 战绩，也必须补齐 14 年历史交锋 (h2h) 与五大联赛当季 Understat xG (season)；
  * 全程 try/except —— 这一步失败绝不能让同步流水线中断；
  * 索引按文件 mtime 缓存 —— 一分钟跑一次不会反复读 8 万行 CSV。
"""
import os
import time
from datetime import datetime, timedelta

import team_stats as TS

_CACHE = {"mtime": None, "idx": None}
TOP5_LEAGUES = {"英超", "德甲", "西甲", "意甲", "法甲"}


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


def _attach_understat_season(blk, home, away, league):
    """为五大联赛场次挂载 Understat 当季 xG 数据。"""
    if league not in TOP5_LEAGUES:
        return False
    try:
        import fetch_understat as _us
        _d = _us.load()
        if _d and league in _d.get("leagues", {}):
            _h = _us.team_season(home, league, _d)
            _a = _us.team_season(away, league, _d)
            if _h or _a:
                blk["season"] = {
                    "home": _h,
                    "away": _a,
                    "updated_at": _d.get("updated_at"),
                    "season": _d.get("season")
                }
                return True
    except Exception:
        pass
    return False


def enrich(matches, limit=120, refresh_hours=12):
    """就地给 matches 补 stats（保护新鲜战绩不被旧数据降级，并强制补齐五大联赛 season xG）。"""
    idx = _index()
    if not idx:
        return 0
    now = datetime.now()
    n = 0
    for m in matches:
        if n >= limit:
            break
        home, away = m.get("home"), m.get("away")
        league = m.get("league") or ""
        day = full_date(m.get("time"))
        if not home or not away or not day:
            continue

        existing = m.get("stats") if isinstance(m.get("stats"), dict) else None
        if existing:
            # 若五大联赛缺失 season xG，立即补齐
            need_season = (league in TOP5_LEAGUES) and not existing.get("season")
            need_h2h = "h2h" not in existing
            ts = m.get("stats_ts")
            fresh = False
            if ts:
                try:
                    fresh = (now - datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")).total_seconds() < refresh_hours * 3600
                except Exception:
                    fresh = False
            if fresh and not need_season and not need_h2h:
                continue

        try:
            blk = TS.build(home, away, day, idx)
        except Exception:
            blk = {}

        if existing:
            # 保护已有的新鲜战绩（如 FotMob 实时全赛事战绩），只有当 CSV 的 last_date 更新时才替换
            merged = dict(existing)
            for side in ("home", "away"):
                cur_side = existing.get(side)
                csv_side = blk.get(side)
                if not cur_side and csv_side:
                    merged[side] = csv_side
                elif cur_side and csv_side:
                    cur_dt = str(cur_side.get("last_date") or "")
                    csv_dt = str(csv_side.get("last_date") or "")
                    if csv_dt > cur_dt:
                        merged[side] = csv_side
            if blk.get("h2h") and not merged.get("h2h"):
                merged["h2h"] = blk["h2h"]
            elif "h2h" not in merged:
                merged["h2h"] = blk.get("h2h")
            _attach_understat_season(merged, home, away, league)
            m["stats"] = merged
            m["stats_ts"] = now.strftime("%Y-%m-%d %H:%M:%S")
            n += 1
            continue

        if not (blk.get("home") or blk.get("away")):
            # 即使历史库无交手，若是五大联赛也尝试挂当季 xG
            if _attach_understat_season(blk, home, away, league):
                m["stats"] = blk
                m["stats_ts"] = now.strftime("%Y-%m-%d %H:%M:%S")
                n += 1
            continue

        _attach_understat_season(blk, home, away, league)
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
    changed = enrich(ms, limit=len(ms), refresh_hours=0 if force else 12)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print(f"enriched {changed}/{len(ms)} matches -> {path}")
