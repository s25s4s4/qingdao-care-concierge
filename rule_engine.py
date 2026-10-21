# -*- coding: utf-8 -*-
"""不用大模型的研判引擎：全部结论由赔率 + 本地历史库 + xG 现算。

为什么要有它
------------
原来的 `deep_reasoning_engine.run_tri_model_deep_reasoning()` 每加一场新比赛就要
调一次 LLM（gemini-3.8-flash-low），token 顶不住。而实际上：

* **推荐方向**本来就被 `sync_live_matches.py` 里的「铁壁守门员」按去水概率覆盖了；
* **比分 / 进球数**也是按 tip 方向从泊松分布里挑的；
* LLM 真正只贡献了四段文案 + 一个共识分。

所以只要能用数字把四段文案写出来，LLM 就可以整条拿掉。

原则
----
1. **只陈述能算出来的东西**：近况、交锋、泊松分布、去水概率、抽水率、xG 偏差。
   不编"战术阵眼""更衣室暗流"这种没有数据支撑的话。
2. 数字必须和详情页展示的一致，避免"文案说 57%、卡片说 69%"的自相矛盾。
3. 任何一项数据缺失就不写那一句，不硬凑。
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
CALIB = os.path.join(HERE, "data", "calibration.json")


# --------------------------------------------------------------------------
# 数学层：复用 deep_reasoning_engine 里的纯计算（不涉及任何网络调用）
# --------------------------------------------------------------------------
def _poisson(odds, league="", is_only_rq=False, rang="0"):
    from deep_reasoning_engine import compute_poisson_and_kelly
    return compute_poisson_and_kelly(odds, league=league, is_only_rq=is_only_rq, rang=rang)


def _goal_bands(lambda_h, mu_a):
    """按总进球分布切成 0-1 / 2-3 / 4+ 三档，并给出期望总进球"""
    import math
    ph = [math.exp(-lambda_h) * lambda_h ** k / math.factorial(k) for k in range(11)]
    pa = [math.exp(-mu_a) * mu_a ** k / math.factorial(k) for k in range(11)]
    bands = [0.0, 0.0, 0.0]
    for x in range(11):
        for y in range(11):
            g = x + y
            p = ph[x] * pa[y]
            bands[0 if g <= 1 else (1 if g <= 3 else 2)] += p
    return [round(b * 100, 1) for b in bands], round(lambda_h + mu_a, 2)


def _score_probs(lambda_h, mu_a, upto=5):
    import math
    ph = [math.exp(-lambda_h) * lambda_h ** k / math.factorial(k) for k in range(upto + 1)]
    pa = [math.exp(-mu_a) * mu_a ** k / math.factorial(k) for k in range(upto + 1)]
    out = []
    for x in range(upto + 1):
        for y in range(upto + 1):
            out.append((f"{x}-{y}", ph[x] * pa[y]))
    out.sort(key=lambda kv: -kv[1])
    return out


# --------------------------------------------------------------------------
# 决策层：和 sync_live_matches 的「铁壁守门员」同一套阈值，保证文案与卡片不打架
# --------------------------------------------------------------------------
def decide_tip(ph, pd, pa, is_only_rq=False, rang="0"):
    """返回 (tip, 方向说明)。ph/pd/pa 为 0-1 的去水概率。"""
    try:
        r = int(str(rang))
    except (TypeError, ValueError):
        r = 0

    if is_only_rq:
        # 单开让球：看让球盘口的胜平负
        if ph + pd >= 0.72:
            return ("让胜" if ph >= 0.65 else "让胜/防让平",
                    f"让球盘去水后主侧合计 {round((ph + pd) * 100, 1)}%，门槛虽在但主队覆盖概率占优")
        if pa + pd >= 0.72:
            return ("让负" if pa >= 0.65 else "让负/防让平",
                    f"让球盘去水后客侧合计 {round((pa + pd) * 100, 1)}%，主队打穿难度偏高")
        return ("让负" if pa >= ph else "让胜",
                f"让球盘去水主 {round(ph * 100, 1)}% / 客 {round(pa * 100, 1)}%，两侧接近，按高侧取")

    if ph + pd >= 0.72:
        return ("主胜" if ph >= 0.65 else "主胜/防平",
                f"去水后主胜 {round(ph * 100, 1)}%、平局 {round(pd * 100, 1)}%，主侧合计 {round((ph + pd) * 100, 1)}%")
    if pa + pd >= 0.72:
        return ("客胜" if pa >= 0.65 else "客胜/防平",
                f"去水后客胜 {round(pa * 100, 1)}%、平局 {round(pd * 100, 1)}%，客侧合计 {round((pa + pd) * 100, 1)}%")
    if pd >= 0.30 and abs(ph - pa) <= 0.06:
        return ("平局/防冷",
                f"去水后主 {round(ph * 100, 1)}% / 平 {round(pd * 100, 1)}% / 客 {round(pa * 100, 1)}%，三向接近，平局权重最高")
    return ("主不败/首选主胜" if ph >= pa else "客不败/首选客胜",
            f"去水后主 {round(ph * 100, 1)}% vs 客 {round(pa * 100, 1)}%，无明显强弱，取不败一侧")


def pick_scores(tip, scores):
    """按 tip 方向从泊松高频比分里挑 3 个，方向必须自洽"""
    win_h = [s for s, _ in scores if int(s.split("-")[0]) > int(s.split("-")[1])]
    win_a = [s for s, _ in scores if int(s.split("-")[1]) > int(s.split("-")[0])]
    draw = [s for s, _ in scores if int(s.split("-")[0]) == int(s.split("-")[1])]

    if tip.startswith("主胜"):
        picks = win_h[:2] + (draw[:1] if "防平" in tip else win_h[2:3])
    elif tip.startswith("客胜"):
        picks = win_a[:2] + (draw[:1] if "防平" in tip else win_a[2:3])
    elif tip.startswith("平局"):
        picks = draw[:2] + (win_h[:1] or win_a[:1])
    elif tip.startswith("主不败"):
        picks = win_h[:2] + draw[:1]
    elif tip.startswith("客不败"):
        picks = win_a[:2] + draw[:1]
    elif tip.startswith("让胜"):
        picks = win_h[:3]
    else:
        picks = (win_a[:2] + draw[:1])
    seen, out = set(), []
    for s in picks:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out[:3] or ["1-0", "1-1", "0-1"]


def pick_goals(bands_lam, scores):
    """进球区间取泊松里概率最高的两档（0-7 展开后取 top2 相邻）"""
    import math
    lam_h, mu_a = bands_lam
    ph = [math.exp(-lam_h) * lam_h ** k / math.factorial(k) for k in range(9)]
    pa = [math.exp(-mu_a) * mu_a ** k / math.factorial(k) for k in range(9)]
    goals = [0.0] * 8
    for x in range(9):
        for y in range(9):
            goals[min(x + y, 7)] += ph[x] * pa[y]
    top = sorted(range(8), key=lambda i: -goals[i])[:2]
    top.sort()
    return [str(i) for i in top]


# --------------------------------------------------------------------------
# 文案层
# --------------------------------------------------------------------------
def _form_text(blk, name):
    if not blk or not blk.get("recent"):
        return ""
    r = blk["recent"]
    txt = f"{name}近{r['n']}场 {r['w']}胜{r['d']}平{r['l']}负、场均 {r['gf']:.2f}:{r['ga']:.2f}"
    if blk.get("stale_days") and blk["stale_days"] > 60:
        txt += f"（数据截至 {blk.get('last_date')}）"
    return txt


def _season_text(t):
    if not t or not t.get("gp"):
        return ""
    gap = t.get("gf", 0) - (t.get("xg") or 0)
    txt = f"本季 {t['gp']} 轮 {t['w']}-{t['d']}-{t['l']}、进 {t['gf']} 失 {t['ga']}"
    if t.get("xg") is not None:
        txt += f"，xG {t['xg']:.1f}"
        if abs(gap) >= 3:
            txt += f"（实际进球{'高出' if gap > 0 else '低于'}期望 {abs(gap):.1f}）"
    return txt


def _calib_text():
    try:
        with open(CALIB, encoding="utf-8") as f:
            c = json.load(f)
        o = c.get("overall") or {}
        if o.get("n", 0) >= 30:
            return f"本站赛前冻结样本 {o['n']} 场，实际命中率 {o['hit_rate']}%"
    except Exception:
        pass
    return ""


def build(match_info, team_stats=None, understat=None):
    """生成与 LLM 版本同契约的 dict。team_stats/understat 可传可不传。"""
    home = match_info.get("home", "主队")
    away = match_info.get("away", "客队")
    league = match_info.get("league", "")
    odds = match_info.get("odds") or ["2.50", "3.20", "2.80"]
    is_only_rq = bool(match_info.get("is_only_rq"))
    rang = str(match_info.get("rang") or "0")

    st = _poisson(odds, league=league, is_only_rq=is_only_rq, rang=rang)
    ph, pd, pa = st["pure_h"] / 100.0, st["pure_d"] / 100.0, st["pure_a"] / 100.0
    lam_h, mu_a = st["lambda_h"], st["mu_a"]

    tip, why = decide_tip(ph, pd, pa, is_only_rq, rang)
    sp = _score_probs(lam_h, mu_a)
    scores = pick_scores(tip, sp)
    goals = pick_goals((lam_h, mu_a), sp)
    bands, total_goals = _goal_bands(lam_h, mu_a)

    # ---- 一、基本面：只用真实近况/交锋/当季数据 ----
    parts = []
    if team_stats:
        for side, nm in (("home", home), ("away", away)):
            t = _form_text(team_stats.get(side), nm)
            if t:
                parts.append(t)
        h2h = team_stats.get("h2h") or {}
        if h2h.get("n"):
            parts.append(f"两队近{h2h['n']}次交锋 {home} {h2h['a_win']}胜{h2h['draw']}平{h2h['b_win']}负、"
                         f"总进球 {h2h['a_goals']}:{h2h['b_goals']}")
    if understat:
        for side, nm in (("home", home), ("away", away)):
            t = _season_text(understat.get(side))
            if t:
                parts.append(f"{nm}{t}")
    fundamental = "；".join(parts) + "。" if parts else \
        f"{home} 与 {away} 暂无可用近期数据，本场仅按官方赔率结构研判。"

    # ---- 二、进球格局：泊松分布，纯数学 ----
    tactical = (f"泊松期望 {home} {lam_h} 球、{away} {mu_a} 球，合计 {total_goals} 球。"
                f"总进球分布：0-1 球 {bands[0]}%、2-3 球 {bands[1]}%、4 球以上 {bands[2]}%。"
                f"理论高频比分 {'、'.join(s for s, _ in sp[:3])}。")

    # ---- 三、机构态度：真实 SP 与去水 ----
    market = (f"官方 SP {st['sp_h']} / {st['sp_d']} / {st['sp_a']}，"
              f"去水后主胜 {st['pure_h']}%、平局 {st['pure_d']}%、客胜 {st['pure_a']}%，"
              f"机构抽水 {st['margin']}%。")
    cal = _calib_text()
    if cal:
        market += cal + "。"

    # ---- 四、决策：把 tip / 进球 / 比分讲清楚 ----
    decision = (f"{why}。首选【{tip}】，进球区间 {'、'.join(g + '球' for g in goals)}，"
                f"比分参考 {'、'.join(scores)}。")
    if is_only_rq:
        decision += f"本场为单开让球（主让/受让 {rang} 球），只看让球盘口，不涉及普通胜平负。"

    # ---- 共识分：全部由可复算的量构成 ----
    odds_score = st["odds_score"]
    concentration = sp[0][1] * 100                      # 最高频比分的概率
    math_score = round(min(max(50 + concentration * 1.6, 55), 88), 1)
    intel_score = 60.0
    if team_stats and (team_stats.get("home") or team_stats.get("away")):
        intel_score += 8
    if understat and (understat.get("home") or understat.get("away")):
        intel_score += 7
    tipster_score = 60.0
    ratio = round(odds_score * 0.45 + math_score * 0.25 + intel_score * 0.15 + tipster_score * 0.15, 1)

    return {
        "tip": tip,
        "consensus_ratio": ratio,
        "consensus_breakdown": {
            "odds_score": odds_score,
            "intel_score": round(intel_score, 1),
            "tipster_score": round(tipster_score, 1),
            "math_score": math_score,
        },
        "predicted_goals": goals,
        "predicted_scores": scores,
        "fundamental": fundamental,
        "tactical_conflict": tactical,
        "market_attitude": market,
        "decision_guide": decision,
        "engine": "rule",
    }


if __name__ == "__main__":
    demo = {"code": "周三004", "league": "欧冠", "home": "科莫", "away": "曼联",
            "odds": ["2.10", "3.40", "3.20"], "rang": "0"}
    r = build(demo)
    for k, v in r.items():
        print(f"{k}: {v}")
