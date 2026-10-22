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
    url = "https://trade.500.com/jczq/"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    team_id_map = {}
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            html = r.read().decode("gbk", errors="ignore")
        teams = re.findall(r'<a href="https://liansai\.500\.com/team/(\d+)/"[^>]*>([^<]+)</a>', html)
        for tid, name in teams:
            tname = name.strip()
            if tname not in team_id_map:
                team_id_map[tname] = tid
    except Exception as e:
        print(f"[LiveForm] Failed to fetch team id map: {e}")
    return team_id_map

def fetch_single_team_form(team_id, team_name):
    url = f"https://liansai.500.com/team/{team_id}/"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            html = r.read().decode("gbk", errors="ignore")
    except Exception:
        return None

    rows = re.findall(
        r'<td class="td_time">(\d{4}-\d{2}-\d{2})</td>\s*<td class="td_lteam"><a[^>]*>([^<]+)</a></td>\s*<td>\s*<span[^>]*>(\d+)</span>:(\d+).*?<td class="td_rteam"><a[^>]*>([^<]+)</a>',
        html,
        re.DOTALL
    )
    if not rows:
        return None

    w, d, l = 0, 0, 0
    gf, ga = 0, 0
    form = []
    
    # 归一化队名简称匹配
    core_name = team_name.replace("FC", "").replace("RB", "").strip()

    for dt, lt, hg, ag, rt in rows[:10]:
        try:
            hg, ag = int(hg), int(ag)
        except:
            continue
        is_home = (core_name in lt or lt in core_name)
        my_g = hg if is_home else ag
        op_g = ag if is_home else hg
        gf += my_g
        ga += op_g
        if my_g > op_g:
            w += 1
            form.append("W")
        elif my_g == op_g:
            d += 1
            form.append("D")
        else:
            l += 1
            form.append("L")

    n = len(rows[:10])
    home_games, away_games = [], []
    for dt, lt, hg, ag, rt in rows[:10]:
        if (core_name in lt or lt in core_name):
            home_games.append((dt, lt, hg, ag, rt))
        else:
            away_games.append((dt, lt, hg, ag, rt))

    def _split(games):
        w = d = l = gf = ga = 0
        form = []
        for dt, lt, hg, ag, rt in games:
            try:
                hg, ag = int(hg), int(ag)
            except (ValueError, TypeError):
                continue
            is_home = (core_name in lt or lt in core_name)
            my_g, op_g = (hg, ag) if is_home else (ag, hg)
            gf += my_g
            ga += op_g
            if my_g > op_g:
                w += 1; form.append("W")
            elif my_g == op_g:
                d += 1; form.append("D")
            else:
                l += 1; form.append("L")
        m = len(games)
        if m == 0:
            return None
        return {"n": m, "w": w, "d": d, "l": l,
                "gf": round(gf / m, 2), "ga": round(ga / m, 2), "form": form[:5]}

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
        # 真实主/客场拆分（2026-10-22 修复：此前是整体近10场复制三份，数据造假）
        "home": _split(home_games),
        "away": _split(away_games),
        "total": n,
        "last_date": rows[0][0],
        "stale_days": max(0, (datetime.now() - datetime.strptime(rows[0][0], "%Y-%m-%d")).days)
    }

def update_all_live_stats(official_matches_path="E:/euro_intel_web/data/official_matches.json", matches=None):
    if not os.path.exists(official_matches_path):
        return
        
    standalone = matches is None
    if standalone:
        with open(official_matches_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        matches = data.get("matches", [])
    team_ids = get_today_team_id_map()
    print(f"[LiveForm] Fetched {len(team_ids)} online team IDs.")

    # 跨轮缓存：6 小时内的球队近况直接复用，不再每轮重打 500.com
    cache = _load_cache()
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
            if cached and (now_ts - cached_ts) < CACHE_TTL_HOURS * 3600:
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
