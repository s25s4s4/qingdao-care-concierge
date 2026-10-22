# -*- coding: utf-8 -*-
"""
实时抓取 500.com 官方球队近况与真实战绩
彻底消灭"动不动就几个月前甚至400多天前"的老旧离线数据！
"""
import urllib.request
import re
import json
import os
from datetime import datetime

CACHE_FILE = os.path.join(os.path.dirname(__file__), "data", "team_live_form_cache.json")
CACHE_TTL_HOURS = 6   # 球队近况最多 6 小时刷一次，避免每分钟流水线反复打 500.com


def _load_cache():
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache):
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass

def get_today_team_id_map():
    urls = ["http://trade.500.com/jczq/", "https://trade.500.com/jczq/"]
    team_id_map = {}
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=12) as r:
                html = r.read().decode("gbk", errors="ignore")
            teams = re.findall(r'<a href="https?://liansai\.500\.com/team/(\d+)/"[^>]*>([^<]+)</a>', html)
            for tid, name in teams:
                tname = name.strip()
                if tname not in team_id_map:
                    team_id_map[tname] = tid
            if len(team_id_map) > 0:
                break
        except Exception as e:
            print(f"[LiveForm] Failed {url}: {e}")
    return team_id_map

def fetch_single_team_form(team_id, team_name):
    urls = [f"http://liansai.500.com/team/{team_id}/", f"https://liansai.500.com/team/{team_id}/"]
    html = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=8) as r:
                html = r.read().decode("gbk", errors="ignore")
            if html:
                break
        except Exception:
            continue
    if not html:
        return None

    # 行级结构化解析：杜绝原正则写死<span class='red'>导致客胜与平局全部漏算的重大缺陷
    trs = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    if not trs:
        return None

    rows = []
    tid_str = str(team_id)
    core_name = team_name.replace("FC", "").replace("RB", "").strip()

    for tr in trs:
        if "td_time" not in tr:
            continue
        m_dt = re.search(r'<td class="td_time">(\d{4}-\d{2}-\d{2})</td>', tr)
        if not m_dt:
            continue
        dt = m_dt.group(1)

        m_lteam = re.search(r'<td class="td_lteam"><a href="[^"]*team/(\d+)/"[^>]*>([^<]+)</a></td>', tr)
        m_rteam = re.search(r'<td class="td_rteam"><a href="[^"]*team/(\d+)/"[^>]*>([^<]+)</a></td>', tr)
        if not m_lteam or not m_rteam:
            continue

        l_tid, l_name = m_lteam.group(1), m_lteam.group(2).strip()
        r_tid, r_name = m_rteam.group(1), m_rteam.group(2).strip()

        # 匹配任何比分标签（兼容<span class="lred">在冒号左侧、右侧或无span平局格式）
        m_score = re.search(r'<td>\s*(?:<[^>]+>)*\s*(\d+)\s*(?:<[^>]+>)*\s*:\s*(?:<[^>]+>)*\s*(\d+)', tr)
        if not m_score:
            continue
        try:
            hg, ag = int(m_score.group(1)), int(m_score.group(2))
        except (ValueError, TypeError):
            continue

        # 基于team_id绝对精准判定主客场（彻底消除队名简称互不包含导致全负的严重BUG）
        if l_tid == tid_str:
            is_home = True
        elif r_tid == tid_str:
            is_home = False
        else:
            is_home = (core_name in l_name or l_name in core_name)

        my_g = hg if is_home else ag
        op_g = ag if is_home else hg
        my_res = "W" if my_g > op_g else ("D" if my_g == op_g else "L")

        rows.append({
            "date": dt,
            "is_home": is_home,
            "my_g": my_g,
            "op_g": op_g,
            "res": my_res,
            "hg": hg,
            "ag": ag,
            "lt": l_name,
            "rt": r_name
        })

    if not rows:
        return None

    # 截取最近最多 10 场完赛赛事
    recent_10 = rows[:10]
    n = len(recent_10)
    w = sum(1 for r in recent_10 if r["res"] == "W")
    d = sum(1 for r in recent_10 if r["res"] == "D")
    l = sum(1 for r in recent_10 if r["res"] == "L")
    gf = sum(r["my_g"] for r in recent_10)
    ga = sum(r["op_g"] for r in recent_10)
    form = [r["res"] for r in recent_10]

    home_games = [r for r in recent_10 if r["is_home"]]
    away_games = [r for r in recent_10 if not r["is_home"]]

    def _split(games):
        if not games:
            return None
        m = len(games)
        gw = sum(1 for r in games if r["res"] == "W")
        gd = sum(1 for r in games if r["res"] == "D")
        gl = sum(1 for r in games if r["res"] == "L")
        ggf = sum(r["my_g"] for r in games)
        gga = sum(r["op_g"] for r in games)
        return {"n": m, "w": gw, "d": gd, "l": gl,
                "gf": round(ggf / m, 2), "ga": round(gga / m, 2), "form": [r["res"] for r in games[:5]]}

    last_dt_str = recent_10[0]["date"]
    try:
        stale_days = max(0, (datetime.now() - datetime.strptime(last_dt_str, "%Y-%m-%d")).days)
    except Exception:
        stale_days = 0

    return {
        "name": team_name,
        "recent": {
            "n": n,
            "w": w,
            "d": d,
            "l": l,
            "gf": round(gf / max(1, n), 2),
            "ga": round(ga / max(1, n), 2),
            "form": form[:5]
        },
        "home": _split(home_games),
        "away": _split(away_games),
        "total": n,
        "last_date": last_dt_str,
        "stale_days": stale_days
    }

def update_all_live_stats(official_matches_path="E:/euro_intel_web/data/official_matches.json", matches=None, force=False):
    if not os.path.exists(official_matches_path):
        return
        
    standalone = matches is None
    if standalone:
        with open(official_matches_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        matches = data.get("matches", [])
    team_ids = get_today_team_id_map()
    print(f"[LiveForm] Fetched {len(team_ids)} online team IDs.")

    # 跨轮缓存：6 小时内且新鲜的球队近况复用；若 force=True 或记录 >7 天则强制重抓
    cache = {} if force else _load_cache()
    now_ts = datetime.now().timestamp()
    updated_teams = {}
    stale_teams = []
    for m in matches:
        if m.get("result") != "PENDING" and m.get("status") == "已完赛":
            continue
        for tname in {m.get("home", ""), m.get("away", "")}:
            if not tname or tname in updated_teams:
                continue
            cached = (cache.get(tname) or {}).get("data")
            cached_ts = (cache.get(tname) or {}).get("ts", 0)
            is_stale = (cached or {}).get("stale_days", 0) > 7
            if not force and cached and not is_stale and (now_ts - cached_ts) < CACHE_TTL_HOURS * 3600:
                updated_teams[tname] = cached
            else:
                stale_teams.append(tname)

    # 抓取主队最新战绩
    for tname in stale_teams:
        if tname in team_ids:
            res = fetch_single_team_form(team_ids[tname], tname)
            if res:
                updated_teams[tname] = res
                cache[tname] = {"ts": now_ts, "data": res}
                print(f"  -> 实时刷新 [{tname}] 战绩: 近{res['recent']['n']}场 {res['recent']['w']}胜{res['recent']['d']}平{res['recent']['l']}负, 最新日期 {res['last_date']} (距今仅{res['stale_days']}天)")

    if stale_teams:
        _save_cache(cache)

    # 赋入 match
    for m in matches:
        if m.get("result") != "PENDING" and m.get("status") == "已完赛":
            continue
        home = m.get("home", "")
        away = m.get("away", "")
        h_stat = updated_teams.get(home)
        a_stat = updated_teams.get(away)

        if h_stat or a_stat:
            if not m.get("stats"):
                m["stats"] = {}
            if h_stat:
                m["stats"]["home"] = h_stat
                m["form_home"] = h_stat["recent"]["form"]
            if a_stat:
                m["stats"]["away"] = a_stat
                m["form_away"] = a_stat["recent"]["form"]
            m["stats"]["source"] = "500网即时战绩直连"
            m["stats_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if standalone:
        from rule_engine import normalize_match
        from sync_live_matches import write_validated_data
        for m in matches: normalize_match(m)
        write_validated_data(official_matches_path, data)
    print(f"[LiveForm] 本轮成功取得 {len(updated_teams)} 队战绩，其余保留已标注日期的数据。")
    return len(updated_teams)

if __name__ == "__main__":
    update_all_live_stats()
