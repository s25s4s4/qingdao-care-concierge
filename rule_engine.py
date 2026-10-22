# -*- coding: utf-8 -*-
"""统一的玩法、结算、比分与详情契约。缺失数据不编造；历史快照不覆盖。"""
import copy
import json
import math
import os
import re
from datetime import datetime
from functools import lru_cache

HERE = os.path.dirname(os.path.abspath(__file__))
DETAIL_SCHEMA = 2


def parse_score(value):
    m = re.fullmatch(r"\s*(\d+)\s*[-:]\s*(\d+)\s*", str(value or ""))
    return tuple(map(int, m.groups())) if m else None


def parse_rang(value):
    if not re.fullmatch(r"[+-]?\d+", str(value).strip()):
        raise ValueError("让球数缺失或无效")
    return int(str(value).strip())


def selected_outcomes(tip):
    """返回本场明确选择的结果；防冷不是任何结果皆可命中的通配符。"""
    tip = str(tip or "")
    if "让" in tip:
        return "hhad", {i for i, text in enumerate(("让胜", "让平", "让负")) if text in tip}
    if "主不败" in tip:
        return "had", {0, 1}
    if "客不败" in tip:
        return "had", {1, 2}
    out = set()
    if "主胜" in tip: out.add(0)
    if "客胜" in tip: out.add(2)
    if "平" in tip: out.add(1)
    if "胜平" in tip: out.update((0, 1))
    if "平负" in tip: out.update((1, 2))
    return "had", out


def calculate_result(tip, score, is_only_rq=False, rang=None):
    parsed = parse_score(score)
    if parsed is None:
        return "PENDING"
    market, selected = selected_outcomes(tip)
    if not selected or (is_only_rq and market != "hhad"):
        return "PENDING"
    diff = parsed[0] - parsed[1]
    if market == "hhad":
        try:
            diff += parse_rang(rang)
        except ValueError:
            return "PENDING"  # 绝不能猜让球数，也不能把让负默认当成客不败
    outcome = 0 if diff > 0 else 1 if diff == 0 else 2
    return "HIT" if outcome in selected else "MISS"


def implied(odds):
    try:
        raw = list(map(float, odds))
        if len(raw) != 3 or any(not math.isfinite(v) or v <= 1 for v in raw):
            return None
        inv = [1 / v for v in raw]
        total = sum(inv)
        return [v / total for v in inv]
    except (ValueError, TypeError):
        return None


def decide_tip(ph, pd, pa, is_only_rq=False, rang="0"):
    names = ("让胜", "让平", "让负") if is_only_rq else ("主胜", "平局", "客胜")
    probs = [ph, pd, pa]
    high = max(range(3), key=lambda i: probs[i])
    if probs[high] >= .65:
        tip = names[high]
    elif high == 1:
        tip = names[1]
    else:
        tip = names[high] + ("/防让平" if is_only_rq else "/防平")
    why = "赔率去水隐含概率 " + " / ".join(f"{n} {v * 100:.1f}%" for n, v in zip(names, probs))
    return tip, why


def _score_probs(lambda_h, mu_a, upto=12):
    def ps(lam):
        values = [math.exp(-lam)]
        for k in range(1, upto + 1): values.append(values[-1] * lam / k)
        return values
    ph, pa = ps(lambda_h), ps(mu_a)
    return sorted(((f"{x}-{y}", ph[x] * pa[y]) for x in range(upto + 1)
                   for y in range(upto + 1)), key=lambda kv: -kv[1])


@lru_cache(maxsize=512)
def fit_model(probs, rang=0):
    """拟合独立泊松参数；按实际让球数聚合，不使用固定深盘模板或臆造xG。"""
    best = (float("inf"), 1.3, 1.1)
    def loss(h, a):
        ph, pa = [math.exp(-h)], [math.exp(-a)]
        for k in range(1, 16):
            ph.append(ph[-1] * h / k)
            pa.append(pa[-1] * a / k)
        agg = [0., 0., 0.]
        for x, px in enumerate(ph):
            for y, py in enumerate(pa):
                diff = x + rang - y
                agg[0 if diff > 0 else 1 if diff == 0 else 2] += px * py
        return sum((v - target) ** 2 for v, target in zip(agg, probs)), agg
    # 粗网格 + 局部细化；记录误差，拟合值不是实际比赛xG。
    for h in [0.15 + i * .35 for i in range(20)]:
        for a in [0.15 + i * .35 for i in range(20)]:
            err, _ = loss(h, a)
            if err < best[0]: best = (err, h, a)
    for step in (.1, .03):
        center_h, center_a = best[1:]
        for dh in range(-4, 5):
            for da in range(-4, 5):
                h, a = max(.03, center_h + dh * step), max(.03, center_a + da * step)
                err, _ = loss(h, a)
                if err < best[0]: best = (err, h, a)
    h, a = round(best[1], 2), round(best[2], 2)
    _, fitted = loss(h, a)
    return {"lambda_h": h, "lambda_a": a,
            "fit_error_pp": round(max(abs(v - t) for v, t in zip(fitted, probs)) * 100, 2),
            "method": "independent_poisson_odds_fit", "rang": rang}


def pick_scores(tip, scores, rang="0"):
    market, selected = selected_outcomes(tip)
    try:
        r = parse_rang(rang) if market == "hhad" else 0
    except ValueError:
        return []
    groups = {i: [] for i in selected}
    for s, p in scores:
        parsed = parse_score(s)
        if parsed is None: continue
        diff = parsed[0] + r - parsed[1]
        i = 0 if diff > 0 else 1 if diff == 0 else 2
        if i in groups: groups[i].append((s, p))
    # 首选两个比分 + 防选一个；双选各结果均有参考比分，不把让平当走盘退款。
    primary = next((i for i, text in enumerate(("让胜", "让平", "让负") if market == "hhad"
                   else ("主胜", "平局", "客胜")) if tip.startswith(text)), None)
    if primary is None: primary = 0 if "主不败" in tip else 2
    result = groups.get(primary, [])[:2]
    for i in sorted(selected - {primary}): result += groups[i][:1]
    candidates = sorted((item for group in groups.values() for item in group), key=lambda kv: -kv[1])
    for item in candidates:
        if len(result) >= 3: break
        if item not in result: result.append(item)
    return [s for s, _ in result[:3]]


def pick_goals(bands_lam, scores):
    return sorted({str(min(sum(parse_score(s)), 7)) for s in scores if parse_score(s)}, key=int)


def _form_text(blk, name):
    if not blk or not blk.get("recent"): return ""
    r = blk["recent"]
    required = ("n", "w", "d", "l", "gf", "ga")
    if any(k not in r for k in required): return ""
    return (f"{name}近{r['n']}场 {r['w']}胜{r['d']}平{r['l']}负，场均进{r['gf']:.2f}失{r['ga']:.2f}"
            f"（截至{blk.get('last_date') or '日期未提供'}）")


def build(match_info, team_stats=None, understat=None):
    home, away = match_info.get("home", "主队"), match_info.get("away", "客队")
    override = match_info.get("detail_tip")
    market = selected_outcomes(override)[0] if override else ("hhad" if match_info.get("is_only_rq") else "had")
    r = parse_rang(match_info.get("rang")) if market == "hhad" else 0
    odds = match_info.get("odds")
    if market == "hhad" and not match_info.get("is_only_rq"):
        odds = match_info.get("odds_rq")  # 双开比赛的让球建议必须取让球SP，不能禁止合法让球玩法
    probs = implied(odds)
    names = ("让胜", "让平", "让负") if market == "hhad" else ("主胜", "平局", "客胜")
    tip = override or (decide_tip(*probs, market == "hhad", r)[0] if probs else "暂不研判")
    _, selected = selected_outcomes(tip)
    model = dict(fit_model(tuple(probs), r)) if probs else None
    scores = pick_scores(tip, _score_probs(model['lambda_h'], model['lambda_a']), r) if model else []
    goals = pick_goals(None, scores)
    parts = []
    stats = team_stats or match_info.get("stats") or {}
    for side, nm in (("home", home), ("away", away)):
        text = _form_text(stats.get(side), nm)
        if text: parts.append(text)
    fundamental = "；".join(parts) + "。" if parts else "暂无可核验近期战绩；不据此编写伤停、战意或战术结论。"
    if model:
        tactical = (f"独立泊松示意参数：主{model['lambda_h']}、客{model['lambda_a']}。"
                    f"按本场{'让球' if market == 'hhad' else '胜平负'}赔率拟合，最大误差{model['fit_error_pp']}个百分点；"
                    "这是赔率结构的近似示意，不是实测xG，也不是独立预测。")
        market_text = (f"{'让球('+str(r)+')' if market == 'hhad' else '胜平负'} SP " + " / ".join(map(str, odds))
                       + "，去水隐含概率 " + " / ".join(f"{n} {p*100:.1f}%" for n, p in zip(names, probs))
                       + "。隐含概率不代表实际命中率。")
    else:
        tactical = "该玩法赔率缺失，无法可靠生成比分和进球分布，暂不展示。"
        market_text = "本场所选玩法赔率缺失；不使用其他玩法赔率代替。"
    ratio = round(sum(probs[i] for i in selected) * 100, 1) if probs and selected else None
    decision = f"选择【{tip}】。"
    if market == "hhad": decision += f"按主队{r:+d}球结算，只选让球结果。"
    if ratio is not None: decision += f"所选结果赔率隐含合计{ratio}%，非历史命中承诺。"
    if scores: decision += f"比分示意{'、'.join(scores)}，对应总进球{'、'.join('7+' if g == '7' else g for g in goals)}。比分是参考，不算另一项已验证预测。"
    return {"tip": tip, "consensus_ratio": ratio, "consensus_breakdown": None,
            "predicted_goals": goals, "predicted_scores": scores,
            "fundamental": fundamental, "tactical_conflict": tactical,
            "market_attitude": market_text, "decision_guide": decision,
            "engine": "rule", "model": model, "market": market, "market_odds": odds,
            "pure": [round(p*100, 4) for p in probs] if probs else None}


def normalize_match(match):
    """发布前统一派生字段；已锁定比赛不重选方向，不修改prediction_snapshot。

    history 判定包含「已有赛前冻结快照」：冻结即承诺，此后的赔率漂移只更新
    展示用 odds，不得覆盖 tip（2026-10-22 修复：此前冻结后、停售前 tip 会被
    最新赔率反复重算，导致展示/结算与冻结快照三方不一致）。
    """
    before = json.dumps(match, sort_keys=True, ensure_ascii=False)
    history = bool(match.get("locked") or match.get("result") != "PENDING"
                   or (match.get("prediction_snapshot") or {}).get("frozen_at"))
    if match.get("detail_schema") != DETAIL_SCHEMA:
        fields = ("tip", "predicted_scores", "predicted_goals", "consensus", "consensus_ratio", "dossier", "quant_factors", "result")
        match.setdefault("detail_original", {k: copy.deepcopy(match.get(k)) for k in fields})
        match["detail_correction"] = {"at": datetime.now().isoformat(timespec="seconds"),
            "reason": "统一玩法与详情展示；保留原始快照及原文，派生说明不是新赛前预测"}
    # 历史无盘口的“让负”旧结算器按客不败处理：显式标注兼容口径，
    # 不由赛果反推选择，不编造缺失的让球数，原标签/原快照保留可审计。
    if history and not match.get('is_only_rq') and '让' in str(match.get('tip')):
        try:
            parse_rang(match.get('rang'))
        except ValueError:
            if match.get('tip') == '让负':
                match['tip'] = '客不败/首选客胜'
                match['legacy_market_correction'] = {
                    'from': '让负', 'to': match['tip'],
                    'reason': '历史未记录让球数，原结算器按客不败核验；仅修正标注，不证明原玩法可购'}
                prov = match.setdefault('provenance', {})
                note = '历史缺少让球盘口，按原系统客不败结算口径修正标注；原始标签留存。'
                if note not in str(prov.get('note') or ''):
                    prov['note'] = str(prov.get('note') or '') + '｜' + note
    info = dict(match)
    snap = match.get("prediction_snapshot") or {}
    frozen_pre = (snap.get("frozen_at") and not snap.get("frozen_mid_match")
                  and snap.get("verified_pre_match") is not False)
    if history: info["detail_tip"] = str(match.get("tip") or "暂不研判")
    if frozen_pre:
        # 案卷按【冻结时】的赔率/让球数重建：tip 是冻结时承诺的，周边数字也必须
        # 同源，否则会出现「主胜45.4%…选择【客胜】」这种自相矛盾的展示
        # （2026-10-22 周四008 实测：冻结时客胜1.81是热门，冻结后主胜1.81→1.95
        #  变热门，tip 按承诺保持客胜，但案卷用了新赔率）。实时赔率在详情页
        # 另有展示位，不丢信息。
        ev = snap.get("evidence") or {}
        ev_odds = ev.get("odds")
        if isinstance(ev_odds, list) and len(ev_odds) == 3:
            info["odds"] = ev_odds
        if snap.get("is_only_rq"):
            info["is_only_rq"] = True
            if snap.get("rang") is not None:
                info["rang"] = snap.get("rang")
    stats = copy.deepcopy(match.get("stats") or {})
    # 历史详情不能注入开赛后的最新近况；不冒充当时可用数据。
    if history:
        kickoff = str(match.get("time") or "")[:5]
        for side in ("home", "away"):
            last = str((stats.get(side) or {}).get("last_date") or "")
            if not last or last[5:10] >= kickoff: stats.pop(side, None)
        stats.pop("season", None)
    try:
        rr = build(info, team_stats=stats)
    except ValueError:
        # 盘口未知时停止推演，不能猜-1或0。
        match["detail_error"] = "让球数缺失，待核验"
        match["predicted_scores"], match["predicted_goals"] = [], []
        match["detail_model"], match["detail_pure"] = None, None
        match["consensus"] = str(match.get("tip") or "暂不研判")
        match["dossier"] = {k: "让球数缺失，待核验；暂不展示此项分析。" for k in
                            ("summary", "fundamental", "tactical_conflict", "market_attitude", "decision_guide")}
        match["detail_schema"] = DETAIL_SCHEMA
        return before != json.dumps(match, sort_keys=True, ensure_ascii=False)
    if not history: match["tip"] = rr["tip"]
    # 比分统一 'H-A' 无空格格式（FotMob 回带空格的 '4 - 3'，显示与比对要一致）
    if match.get("score") and str(match["score"]) not in ("--", "延期"):
        match["score"] = str(match["score"]).replace(" ", "")
    match["prediction_market"] = rr["market"]
    match["detail_market_odds"] = rr["market_odds"]
    match["detail_model"] = rr["model"]
    match["detail_pure"] = rr["pure"]
    match["predicted_scores"], match["predicted_goals"] = rr["predicted_scores"], rr["predicted_goals"]
    match["consensus_ratio"] = rr["consensus_ratio"]
    match["consensus_breakdown"] = None
    match["consensus"] = str(match.get("tip") or "暂不研判")
    match["dossier"] = {k: rr[k] for k in ("fundamental", "tactical_conflict", "market_attitude", "decision_guide")}
    # 冻结后赔率若发生变动，在案卷里显式说明，避免彩民以为推荐跟着最新赔率
    if frozen_pre:
        ev_odds = (snap.get("evidence") or {}).get("odds")
        live_odds = match.get("odds")
        if (isinstance(ev_odds, list) and len(ev_odds) == 3 and isinstance(live_odds, list)
                and len(live_odds) == 3
                and [str(x) for x in ev_odds] != [str(x) for x in live_odds]):
            match["dossier"]["market_attitude"] += (
                f"（注意：此为冻结时赔率；截至当前最新即时赔率已变动为 "
                f"{' / '.join(str(x) for x in live_odds)}，推荐以赛前冻结为准，不随盘口漂移。）")
    match["dossier"]["summary"] = f"{match.get('home')}对阵{match.get('away')}，{match['consensus']}。"
    match["analysis"] = match["dossier"]["summary"]
    match["stats"] = stats
    if history and not stats.get('home') and not stats.get('away'):
        match['form_home'] = []
        match['form_away'] = []
    q = match.get("quant_factors")
    if match.get("is_only_rq"):
        match["quant_factors"] = None  # 无让球历史样本库，不能从标准赔率桶伪造概率
    elif q:
        q["market"] = "had"
        q["smart_pick"] = None
        q["quant_detail_note"] = "历史赔率邻域频率仅作独立参考；非相同赔率、非本场命中率，不替代本场玩法研判。"
    if match.get("result") in ("HIT", "MISS") and parse_score(match.get("score")):
        result = calculate_result(match.get("tip"), match["score"], match.get("is_only_rq"), match.get("rang"))
        if result in ("HIT", "MISS"):
            match["result"] = result
            match["result_text"] = "研判命中" if result == "HIT" else "研判未中"
            match["status"] = "已完赛"
            if match.get("settlement"):
                match["settlement"]["result"] = result
    match["detail_schema"] = DETAIL_SCHEMA
    match.pop("detail_error", None)
    return before != json.dumps(match, sort_keys=True, ensure_ascii=False)


def settle_identity(match):
    """结算与校验的统一口径：有【赛前】冻结快照时，tip / 玩法 / 让球数一律取快照。

    冻结即承诺。停售前赔率漂移可以更新展示用 odds，但不得改变被评判的预测；
    已结算场次按快照重算，不用冻结后漂移出来的当前 tip（2026-10-22 修复）。
    开赛中冻结的快照（frozen_mid_match）不是赛前承诺，按当前 tip 结算，
    与校准统计「开赛后冻结不进主口径」保持一致。
    """
    snap = match.get("prediction_snapshot") or {}
    pre_match = (snap.get("frozen_at")
                 and not snap.get("frozen_mid_match")
                 and snap.get("verified_pre_match") is not False)
    if pre_match:
        return (str(snap.get("tip") or match.get("tip") or ""),
                bool(snap.get("is_only_rq")),
                snap.get("rang", "0"))
    return (str(match.get("tip") or ""), bool(match.get("is_only_rq")), match.get("rang"))


def validate_matches(matches):
    issues, identities = [], set()
    for m in matches:
        ident = (m.get("code"), m.get("time"), m.get("home"), m.get("away"))
        if ident in identities: issues.append((m.get("code"), "重复赛事"))
        identities.add(ident)
        tip, is_only_rq, rang = settle_identity(m)
        market, selected = selected_outcomes(tip)
        if is_only_rq and market != "hhad": issues.append((m.get("code"), "单开让球却选择普通胜平负"))
        if not str(m.get("consensus") or "").startswith(tip): issues.append((m.get("code"), "推荐与摘要冲突"))
        for s in m.get("predicted_scores") or []:
            if calculate_result(tip, s, is_only_rq, rang) != "HIT":
                issues.append((m.get("code"), "比分未覆盖所选玩法: " + s))
            parsed = parse_score(s)
            if parsed and str(min(sum(parsed), 7)) not in (m.get("predicted_goals") or []):
                issues.append((m.get("code"), "进球区间未覆盖比分: " + s))
        if m.get("result") in ("HIT", "MISS") and calculate_result(tip, m.get("score"), is_only_rq, rang) != m.get("result"):
            issues.append((m.get("code"), "结算与选择冲突"))
        if m.get("detail_schema") != DETAIL_SCHEMA: issues.append((m.get("code"), "详情未经过校验"))
    return issues
