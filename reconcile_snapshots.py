# -*- coding: utf-8 -*-
"""一次性订正（2026-10-22）：让「冻结快照」成为唯一的展示与结算口径。

背景：rule_engine 重写前，快照冻结的是旧引擎 tip；重写后 normalize_match 对
未锁定比赛每轮用最新赔率重算 tip，导致 85/111 场「快照 tip != 当前 tip」，
而结算（verify.settle）用的是当前 tip——站点承诺的「以赛前冻结记录为准」
实际没有兑现。

本脚本做三件事（可重复跑，幂等）：
  1. 有快照的场次：tip 对齐为快照 tip（此后 normalize_match 不再覆盖）；
  2. 已结算场次：按快照 tip/rang/is_only_rq 重算 HIT/MISS，记录订正痕迹；
  3. 统一过 normalize_match + validate_matches + 原子写。

不删快照、不改比分——快照是开赛前的真实承诺，比分以比分为准。
"""
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DATA = os.path.join(HERE, "data", "official_matches.json")

import rule_engine as r


def main(apply_write=True):
    with open(DATA, encoding="utf-8") as f:
        data = json.load(f)
    matches = data.get("matches", [])

    aligned = flipped = unchanged = no_snap = 0
    flips = []

    for m in matches:
        snap = m.get("prediction_snapshot") or {}
        # 只对齐【赛前】冻结快照；开赛中冻结的（frozen_mid_match）不是赛前承诺，保持当前 tip
        pre_match = (snap.get("frozen_at")
                     and not snap.get("frozen_mid_match")
                     and snap.get("verified_pre_match") is not False)
        if not pre_match:
            no_snap += 1
            continue

        snap_tip = str(snap.get("tip") or "")
        if snap_tip and snap_tip != str(m.get("tip") or ""):
            m["tip"] = snap_tip
            m["tip_aligned_to_snapshot"] = {
                "at": datetime.now().isoformat(timespec="seconds"),
                "reason": "展示口径对齐赛前冻结快照（2026-10-22 一次性订正）",
            }
            aligned += 1

        if m.get("result") in ("HIT", "MISS") and r.parse_score(m.get("score")):
            new_res = r.calculate_result(
                snap_tip, m.get("score"),
                bool(snap.get("is_only_rq")), snap.get("rang", "0"),
            )
            if new_res in ("HIT", "MISS") and new_res != m.get("result"):
                old = m["result"]
                m["result"] = new_res
                m["result_text"] = "研判命中" if new_res == "HIT" else "研判未中"
                st = m.get("settlement") or {}
                st.update({
                    "result": new_res,
                    "tip": snap_tip,
                    "reconciled_at": datetime.now().isoformat(timespec="seconds"),
                    "reconciled_from": old,
                    "note": "按赛前冻结快照 tip 重算（此前按冻结后漂移的 tip 结算）",
                })
                m["settlement"] = st
                flipped += 1
                flips.append((m.get("code"), m.get("home"), old, new_res, snap_tip))
            elif new_res == m.get("result"):
                st = m.get("settlement") or {}
                if st.get("tip") != snap_tip:
                    st["tip"] = snap_tip
                    st["reconciled_at"] = datetime.now().isoformat(timespec="seconds")
                    st["note"] = "按赛前冻结快照 tip 复核，结果不变"
                    m["settlement"] = st
                unchanged += 1

    for m in matches:
        r.normalize_match(m)

    issues = r.validate_matches(matches)
    if issues:
        print("!! 订正后未通过发布检查，放弃写盘:")
        for i in issues[:10]:
            print("   ", i)
        return 1

    if apply_write:
        data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data["total"] = len(matches)
        data["matches"] = matches
        tmp = DATA + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, DATA)
        print(f"已写盘 {DATA}")

    print(f"快照缺失场次: {no_snap} | tip 对齐: {aligned} | 结果翻转: {flipped} | 复核不变: {unchanged}")
    for code, home, old, new, tip in flips:
        print(f"  [翻转] {code} {home}: {old} -> {new}（快照 tip={tip}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(apply_write="--dry-run" not in sys.argv))
