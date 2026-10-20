# -*- coding: utf-8 -*-
"""从本地 14 年竞彩历史数据里，算出球队的真实近期数据。

为什么用这个源而不是 FBref / Understat：
  * 球队名是中文，和站点数据天然对齐，不需要维护翻译表；
  * 80,000+ 场、2,130 支球队，14 年跨度，H2H 样本够；
  * 不依赖外网，不会被反爬打断，跑在计划任务里也稳。

输出直接挂到 match["stats"]，供详情弹窗渲染。
用法：
    python team_stats.py "费内巴切" "斯拉维亚" "2026-10-20"
    python team_stats.py --demo
"""
import csv
import sys
import os
from datetime import datetime
from collections import defaultdict

CSV = os.environ.get("JC_CSV", r"C:/Users/Administrator/Desktop/竞彩历史数据/竞彩数据14年至今.csv")
KEYS = ("胜", "平", "负")


def _f(s):
    try:
        v = float(s)
        return v if v > 0 else None
    except Exception:
        return None


def load(path=CSV):
    """返回按球队索引的比赛列表：{team: [ {date, lg, home, away, hg, ag, res, ...} ]}"""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        hdr = next(rd)
        rows = [r for r in rd if len(r) >= 22]
    H = {h: i for i, h in enumerate(hdr)}

    def g(r, k):
        return r[H[k]].strip()

    idx = defaultdict(list)
    for r in rows:
        res = g(r, "赛果")
        if res not in KEYS:
            continue
        vs = g(r, "主客场")
        if " VS " not in vs:
            continue
        home, away = [x.strip() for x in vs.split(" VS ", 1)]
        sc = g(r, "全场比分").replace(":", "-")
        if "-" not in sc:
            continue
        try:
            hg, ag = [int(x) for x in sc.split("-")[:2]]
        except Exception:
            continue
        dt = g(r, "比赛时间")[:10]
        item = {"date": dt, "lg": g(r, "联赛"), "home": home, "away": away,
                "hg": hg, "ag": ag, "res": res,
                "oh": _f(g(r, "胜")), "od": _f(g(r, "平")), "oa": _f(g(r, "负"))}
        idx[home].append(item)
        idx[away].append(item)
    # 合并赛果归档（data/match_results.jsonl），让库随着流水线不断变长
    try:
        import result_archive
        seen = {(x["date"], x["home"], x["away"]) for v in idx.values() for x in v}
        added = 0
        for it in result_archive.load_items():
            key = (it["date"], it["home"], it["away"])
            if key in seen:
                continue
            seen.add(key)
            idx[it["home"]].append(it)
            idx[it["away"]].append(it)
            added += 1
        if added:
            pass  # 归档合并完成
    except Exception:
        pass

    for k in idx:
        idx[k].sort(key=lambda x: x["date"])
    return idx


def _outcome(item, team):
    """该队在这场的结果：W/D/L"""
    is_home = item["home"] == team
    gf, ga = (item["hg"], item["ag"]) if is_home else (item["ag"], item["hg"])
    return ("W" if gf > ga else "D" if gf == ga else "L"), gf, ga, is_home


def _agg(games, team, limit=None):
    n = w = d = l = 0
    gf = ga = 0
    form = []
    for it in reversed(games):          # 从最近往前
        if limit and n >= limit:
            break
        o, f, a, _ = _outcome(it, team)
        n += 1
        gf += f
        ga += a
        if o == "W":
            w += 1
        elif o == "D":
            d += 1
        else:
            l += 1
        form.append(o)
    if n == 0:
        return None
    return {"n": n, "w": w, "d": d, "l": l,
            "gf": round(gf / n, 2), "ga": round(ga / n, 2),
            "form": form[:5]}


def team_block(idx, team, before, league=None, recent=10):
    """赛前视角：只取 before 之前的比赛。不做时间窗裁剪，但会返回最近一场的日期，
    让前端能明确显示"数据截至哪天"——本地库各联赛覆盖程度不同，藏起来比露出来更危险。"""
    games = [x for x in idx.get(team, []) if x["date"] < before]
    if league:
        same = [x for x in games if x["lg"] == league]
        if len(same) >= 5:
            games = same
    if not games:
        return None
    all10 = _agg(games, team, recent)
    home_g = [x for x in games if x["home"] == team]
    away_g = [x for x in games if x["away"] == team]
    last_date = games[-1]["date"]
    stale_days = None
    try:
        stale_days = (datetime.strptime(before, "%Y-%m-%d") -
                      datetime.strptime(last_date, "%Y-%m-%d")).days
    except Exception:
        pass
    return {
        "name": team,
        "recent": all10,
        "home": _agg(home_g, team, recent),
        "away": _agg(away_g, team, recent),
        "total": len(games),
        "last_date": last_date,
        "stale_days": stale_days,
    }


def h2h_block(idx, a, b, before, limit=8):
    games = [x for x in idx.get(a, [])
             if x["date"] < before and {x["home"], x["away"]} == {a, b}]
    if not games:
        return None
    aw = d = bw = 0
    agf = bgf = 0
    for it in games[-limit:]:
        o, f, gg, is_home = _outcome(it, a)
        agf += f
        bgf += gg
        if o == "W":
            aw += 1
        elif o == "D":
            d += 1
        else:
            bw += 1
    return {"n": len(games[-limit:]), "a_win": aw, "draw": d, "b_win": bw,
            "a_goals": agf, "b_goals": bgf,
            "last": [{"date": it["date"], "score": f'{it["hg"]}-{it["ag"]}',
                      "home": it["home"]} for it in games[-3:]]}


def build(home, away, before, idx=None):
    idx = idx or load()
    return {
        "home": team_block(idx, home, before),
        "away": team_block(idx, away, before),
        "h2h": h2h_block(idx, home, away, before),
        "source": "本地竞彩历史库",
    }


def coverage(windows=(365, 180), idx=None):
    """全库覆盖度：不同时间窗内能凑齐 10 场的球队占比。
    注意这是「库」的覆盖度，不是「归档」的覆盖度 —— 归档只是最近那层。"""
    idx = idx or load()
    from datetime import datetime as _dt, timedelta as _td
    out = {"teams": len(idx), "all": 0}
    for w in windows:
        out[str(w)] = 0
    floors = {w: (_dt.now() - _td(days=w)).strftime("%Y-%m-%d") for w in windows}
    for t, games in idx.items():
        if len(games) >= 10:
            out["all"] += 1
        for w in windows:
            if sum(1 for x in games if x["date"] >= floors[w]) >= 10:
                out[str(w)] += 1
    return out


def _fmt(blk):
    if not blk:
        return "  无数据"
    r = blk["recent"]
    h = blk["home"]
    a = blk["away"]
    s = (f'  近{r["n"]}场 {r["w"]}胜{r["d"]}平{r["l"]}负  场均 {r["gf"]:.2f}:{r["ga"]:.2f}  '
         f'近5走势 {"".join(r["form"])}')
    if h:
        s += f'\n    主场 {h["w"]}胜{h["d"]}平{h["l"]}负 {h["gf"]:.2f}:{h["ga"]:.2f}'
    if a:
        s += f'\n    客场 {a["w"]}胜{a["d"]}平{a["l"]}负 {a["gf"]:.2f}:{a["ga"]:.2f}'
    s += f'\n    库内历史 {blk["total"]} 场，最近一场 {blk["last_date"]}'
    if blk.get("stale_days") and blk["stale_days"] > 60:
        s += f'  ⚠ 距今 {blk["stale_days"]} 天'
    return s


if __name__ == "__main__":
    if "--demo" in sys.argv or len(sys.argv) < 3:
        cases = [
            ("费内巴切", "斯拉维亚", "2026-10-20"),
            ("曼城", "伊普斯", "2026-10-17"),
            ("博洛尼亚", "国际米兰", "2026-10-18"),
        ]
        idx = load()
        print(f"索引球队 {len(idx)} 支\n")
        for h, a, d in cases:
            print(f"=== {h} vs {a}  （赛前 {d}）===")
            r = build(h, a, d, idx)
            print(f"[主] {h}")
            print(_fmt(r["home"]))
            print(f"[客] {a}")
            print(_fmt(r["away"]))
            z = r["h2h"]
            if z:
                print(f"[交锋] 近{z['n']}次：{h} {z['a_win']}胜 {z['draw']}平 {z['b_win']}负"
                      f'  进球 {z["a_goals"]}:{z["b_goals"]}')
                for x in z["last"]:
                    print(f'    {x["date"]}  {x["home"]} 主  {x["score"]}')
            else:
                print("[交锋] 库内无记录")
            print()
    else:
        h, a, d = sys.argv[1], sys.argv[2], sys.argv[3]
        r = build(h, a, d)
        print(f"=== {h} vs {a} （赛前 {d}）===")
        print(f"[主] {h}\n{_fmt(r['home'])}")
        print(f"[客] {a}\n{_fmt(r['away'])}")
        z = r["h2h"]
        print(f"[交锋] {z if z else '库内无记录'}")
