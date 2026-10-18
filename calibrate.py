"""预测质量评估：分置信度区间的真实命中率与校准偏差。
没有这一步，任何"模型改进"都无法验证是否真的变好。
"""
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "data", "calibration.json")
BUCKETS = [(0, 45), (45, 55), (55, 65), (65, 75), (75, 101)]


def _settled(matches):
    out = []
    for m in matches:
        st = m.get("settlement") or {}
        snap = m.get("prediction_snapshot") or {}
        if st.get("result") in ("HIT", "MISS") and snap.get("frozen_at"):
            out.append((m, snap, st))
    return out


def evaluate(matches):
    rows = _settled(matches)
    report = {"generated_at": datetime.now().isoformat(timespec="seconds"),
              "samples": len(rows), "buckets": [], "overall": {}, "by_method": {}}
    if not rows:
        report["note"] = "暂无已结算的冻结预测，无法评估"
        _write(report)
        return report

    hits = sum(1 for _m, _s, st in rows if st["result"] == "HIT")
    report["overall"] = {"hit_rate": round(hits / len(rows) * 100, 2), "n": len(rows)}

    for low, high in BUCKETS:
        group = [(m, s, st) for m, s, st in rows
                 if low <= float(s.get("consensus_ratio") or 0) < high]
        if not group:
            continue
        h = sum(1 for _m, _s, st in group if st["result"] == "HIT")
        claimed = sum(float(s.get("consensus_ratio") or 0) for _m, s, _st in group) / len(group)
        actual = h / len(group) * 100
        report["buckets"].append({"range": f"{low}-{high - 1}", "n": len(group),
                                  "claimed": round(claimed, 1), "actual": round(actual, 1),
                                  "bias": round(actual - claimed, 1)})

    for m, s, st in rows:
        method = (s.get("evidence") or {}).get("method") or "unknown"
        slot = report["by_method"].setdefault(method, {"n": 0, "hit": 0})
        slot["n"] += 1
        if st["result"] == "HIT":
            slot["hit"] += 1
    for method, slot in report["by_method"].items():
        slot["hit_rate"] = round(slot["hit"] / slot["n"] * 100, 2)

    _write(report)
    return report


def _write(report):
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    data = json.load(open(os.path.join(BASE, "data", "official_matches.json"), encoding="utf-8"))
    print(json.dumps(evaluate(data["matches"]), ensure_ascii=False, indent=2))
