# -*- coding: utf-8 -*-
"""一次性追赶（2026-10-22）：把停售前抢跑的旧快照，按停售时点的市场重新冻结。

背景：冻结时机从「入清单即冻」改为「停售才冻」。今晚 13 场周四比赛在 22:00
停售时线上还是旧逻辑，tip 未按停售价刷新，旧快照（10-21 旧引擎口径）仍在。
本脚本对「已停售 + 未开赛 + 快照是抢跑的」场次：
  1. 用当前（停售时点）赔率重新生成推荐（rule_engine.build）；
  2. 调 verify.freeze 作废旧快照、按新推荐落锁（frozen_at_last_sellable）；
  3. normalize 重建案卷并过发布检查后原子写盘。
可重复跑（已有正规快照的场次自动跳过）。
"""
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DATA = os.path.join(HERE, "data", "official_matches.json")

import rule_engine as r
import verify


def main(apply_write=True):
    with open(DATA, encoding="utf-8") as f:
        data = json.load(f)
    matches = data.get("matches", [])

    refrozen, skipped = [], 0
    for m in matches:
        if m.get("result") != "PENDING" or not m.get("sale_closed"):
            continue
        snap = m.get("prediction_snapshot") or {}
        if snap.get("frozen_at_last_sellable"):
            continue  # 已是停售时刻的正规冻结
        if not snap.get("frozen_at"):
            continue  # 从没冻过：交给流水线 freeze 正常处理

        old_tip = snap.get("tip")
        info = dict(m)
        info.pop("detail_tip", None)
        rr = r.build(info)  # 用当前（停售时点）赔率重新生成
        m["tip"] = rr["tip"]
        m["predicted_scores"] = rr["predicted_scores"]
        m["predicted_goals"] = rr["predicted_goals"]
        m["consensus_ratio"] = rr["consensus_ratio"]

        if not verify.freeze(m):
            print(f"  !! {m['code']} freeze 未生效（已开赛？）")
            continue
        r.normalize_match(m)
        refrozen.append((m["code"], m.get("home"), old_tip, m["tip"]))
        skipped += 0

    issues = r.validate_matches(matches)
    if issues:
        print("!! 未通过发布检查，放弃写盘:")
        for i in issues[:10]:
            print("   ", i)
        return 1

    if apply_write and refrozen:
        data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data["total"] = len(matches)
        data["matches"] = matches
        tmp = DATA + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, DATA)
        print(f"已写盘，重冻 {len(refrozen)} 场：")
    for code, home, old, new in refrozen:
        mark = "（有变）" if old != new else "（不变）"
        print(f"  {code} {home}: {old} -> {new} {mark}")
    if not refrozen:
        print("没有需要重冻的场次")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(apply_write="--dry-run" not in sys.argv))
