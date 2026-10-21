# -*- coding: utf-8 -*-
"""复刻网站 index.html 里的 2串1 ROI 算法，输出每天的双轨 ROI。

对应 JS：index.html 第 2039–2200 行
  totalParlayPairs = C(n,2)
  多选轨（网站主口径）：两场 result 都是 HIT 即命中，返还 = sp1*sp2，成本按 1 注/对
  单选轨（对比卡）：每场按 tip 取首选，实际结果等于首选即命中
"""
import json
import itertools
from collections import defaultdict

DATA = r"E:\euro_intel_web\data\official_matches.json"


def sp_of(m):
    """按 JS 逻辑取该场实际结果的 SP。"""
    odds = m.get("odds") or []
    score = (m.get("score") or "").replace(" ", "")
    if "-" not in score or len(odds) < 3:
        return 1.85
    try:
        h, a = [int(x) for x in score.split("-")[:2]]
    except ValueError:
        return 1.85
    if m.get("is_only_rq"):
        rang = int(m.get("rang") or -1)
        diff = h + rang - a
        if diff > 0:
            return float(odds[0]) or 1.85
        if diff == 0:
            return float(odds[1]) or 3.50
        return float(odds[2]) or 2.20
    if h > a:
        return float(odds[0]) or 1.85
    if h == a:
        return float(odds[1]) or 3.20
    return float(odds[2]) or 2.80


def primary_of(m):
    tip = m.get("tip") or ""
    if "首选平" in tip or tip.startswith("平局"):
        return "平局"
    if "首选客胜" in tip or tip.startswith("客胜"):
        return "客胜"
    if "首选主胜" in tip or tip.startswith("主胜"):
        return "主胜"
    if "客不败" in tip:
        return "客胜"
    if "主不败" in tip:
        return "主胜"
    return "主胜"


def actual_of(m):
    score = (m.get("score") or "").replace(" ", "")
    if "-" not in score:
        return None
    h, a = [int(x) for x in score.split("-")[:2]]
    return "主胜" if h > a else ("平局" if h == a else "客胜")


def options_of(m):
    """按 index.html parseMatchTipOptions 的口径，把 tip 解析成投注项集合。"""
    tip = m.get("tip") or ""
    p = "让" if m.get("is_only_rq") else ""
    if "死胆" in tip or "主胜让胜" in tip:
        return {p + "胜"}
    if tip == "主胜":
        return {p + "胜"}
    if tip == "客胜":
        return {p + "负"}
    if tip == "平局":
        return {p + "平"}
    if "让负" in tip:
        return {"让负", "让平"}
    if "让胜" in tip:
        return {"让胜"}
    if "主不败" in tip or "主胜/防平" in tip or "平局/主胜" in tip:
        return {p + "胜", p + "平"}
    if ("客不败" in tip or "客胜/防平" in tip or "平局/客胜" in tip
            or "双选平负" in tip or "首选客胜" in tip or "首选平" in tip
            or "客胜/进球数大" in tip):
        return {p + "负", p + "平"}
    return {p + "负"} if "客" in tip else {p + "胜"}


def main():
    d = json.load(open(DATA, encoding="utf-8"))
    ms = [m for m in d["matches"] if m.get("result") in ("HIT", "MISS") and m.get("score")]
    by_day = defaultdict(list)
    for m in ms:
        by_day[(m.get("time") or "")[:5]].append(m)

    print(f"已结算 {len(ms)} 场，分布在 {len(by_day)} 个比赛日\n")
    print(f"{'比赛日':<8}{'场次':>5}{'组合':>7}{'双选命中':>9}{'双选ROI(网站口径)':>19}{'单选命中':>9}{'单选ROI':>10}")
    tot = {"pairs": 0, "multi_hit": 0, "multi_ret": 0.0, "single_hit": 0, "single_ret": 0.0,
           "stake": 0.0}
    for day in sorted(by_day):
        rows = by_day[day]
        pairs = list(itertools.combinations(rows, 2))
        multi_hit = multi_ret = single_hit = single_ret = 0.0
        for m1, m2 in pairs:
            if m1["result"] == "HIT" and m2["result"] == "HIT":
                multi_hit += 1
                multi_ret += sp_of(m1) * sp_of(m2)
            if actual_of(m1) == primary_of(m1) and actual_of(m2) == primary_of(m2):
                single_hit += 1
                single_ret += sp_of(m1) * sp_of(m2)
        n = len(pairs)
        if not n:
            continue
        mroi = (multi_ret - n) / n * 100
        sroi = (single_ret - n) / n * 100
        print(f"{day:<8}{len(rows):>5}{n:>7}{int(multi_hit):>9}{mroi:>18.1f}%{int(single_hit):>9}{sroi:>9.1f}%")
        tot["pairs"] += n
        tot["multi_hit"] += multi_hit
        tot["multi_ret"] += multi_ret
        tot["single_hit"] += single_hit
        tot["single_ret"] += single_ret
        for m1, m2 in pairs:
            tot["stake"] += len(options_of(m1)) * len(options_of(m2))

    n = tot["pairs"]
    print("\n=== 合计 ===")
    print(f"组合数 {n}")
    print(f"双选轨：命中 {int(tot['multi_hit'])} ({tot['multi_hit']/n*100:.1f}%)  "
          f"ROI {(tot['multi_ret']-n)/n*100:+.1f}%  （网站口径：双选按 1 注计费）")
    print(f"单选轨：命中 {int(tot['single_hit'])} ({tot['single_hit']/n*100:.1f}%)  "
          f"ROI {(tot['single_ret']-n)/n*100:+.1f}%")
    avg = tot["stake"] / n
    real = (tot["multi_ret"] - tot["stake"]) / tot["stake"] * 100
    print(f"\n双选轨按真实成本：平均 {avg:.2f} 注/对，总注数 {tot['stake']:.0f}，"
          f"**真实 ROI {real:+.1f}%**")
    print("注：双选轨按网站口径，双选不额外计费；真实成本下 ROI 见上一行。")


if __name__ == "__main__":
    main()
