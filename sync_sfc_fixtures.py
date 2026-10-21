# -*- coding: utf-8 -*-
"""传足（胜负彩 14 场）赛程刷新。

背景：原来只有服务器上一个 cron 在跑 `sync_sfc.py`，而那个脚本**只更新已有对阵的比分**，
不会拉新一期。结果 10-19 那期的 14 场一直挂着，页签展示的是两天前的比赛。

本脚本负责「换期」：从 500.com 抓当前期号与 14 场对阵，交给 quant_engine 算因子与选号，
写回 data/sfc_matches.json，然后推 GitHub + scp 阿里云。

设计要点：
  * **赔率没出来就不覆盖**。新一期刚开售时 500 的「平均欧赔」是 "-"，此时不能算量化，
    如果强行写入会把上一期已经算好的选号冲掉。所以：同期且无赔率 → 原样不动。
  * 同期已存在时，保留原 dossier（LLM 生成，重算一次要 14 次调用）。
  * 全流程 try/except，失败不影响别的流水线。
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "sfc_matches.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0 Safari/537.36"


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://trade.500.com/"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("gbk", errors="ignore")


def fetch_current_period():
    """首页里带当期期号的链接，取最大的那个"""
    html = _get("https://trade.500.com/sfc/")
    nums = [int(x) for x in re.findall(r"/sfc/\?expect=(\d+)", html)]
    return max(nums) if nums else None


def parse_fixtures(html):
    """解析 14 场对阵。返回 (matches, odds_ready)"""
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        m_no = re.search(r'class="td td-no">\s*(\d+)', tr)
        if not m_no:
            continue
        no = int(m_no.group(1))

        evt = re.search(r'class="td td-evt"><a[^>]*style="background:(#[0-9A-Fa-f]{6});?"[^>]*>([^<]+)</a>', tr)
        league = evt.group(2).strip() if evt else ""
        color = evt.group(1) if evt else "#666666"

        t = re.search(r'class="td td-endtime">([^<]*)<', tr)
        time_s = t.group(1).strip() if t else ""

        # [排名] 主队  VS  客队 [排名]
        home_rank = re.search(r'<span class="team-l"><i>\[(\d*)\]</i>', tr)
        away_rank = re.search(r'</a><i>\[(\d*)\]</i></span>', tr)
        home = re.search(r'class="team-l">([^<]+)</a>', tr)
        away = re.search(r'class="team-r">([^<]+)</a>', tr)
        if not (home and away):
            continue

        fid = re.search(r"shuju-(\d+)\.shtml", tr)

        # 平均欧赔：<td class="td td-pei"><span>2.10</span> <span>3.20</span> <span>3.40</span>
        pei = re.search(r'class="td td-pei">(.*?)</td>', tr, re.S)
        odds = []
        if pei:
            odds = [x.strip() for x in re.findall(r"<span>([^<]*)</span>", pei.group(1))][:3]

        out.append({
            "no": no,
            "league": league,
            "league_color": color,
            "time": time_s,
            "home": home.group(1).strip(),
            "home_rank": (home_rank.group(1) if home_rank else "").strip(),
            "away": away.group(1).strip(),
            "away_rank": (away_rank.group(1) if away_rank else "").strip(),
            "fid": fid.group(1) if fid else "",
            "status": "未开赛",
            "matched_id": None,
            "odds": odds if len(odds) == 3 and all(o.replace(".", "").isdigit() for o in odds) else [],
            "consensus": "",
            "dossier": {},
            "live_status": "",
            "score": "",
            "pick_primary": None,
            "pick_secondary": None,
            "pick_desc": "",
            "pick_upset": None,
            "quant_factors": {},
            "outcome": "",
            "result": None,
            "result_text": "",
        })
    out.sort(key=lambda x: x["no"])
    odds_ready = bool(out) and all(len(x["odds"]) == 3 for x in out)
    return out, odds_ready


def load_existing():
    if not os.path.exists(OUT):
        return {}
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def build(period, matches, existing):
    """同期则保留 dossier / 已有比分（existing 为空表示换期了）"""
    old = {}
    for m in existing.get("matches", []):
        old[(m.get("home"), m.get("away"))] = m
    for m in matches:
        o = old.get((m["home"], m["away"]))
        if not o:
            continue
        for k in ("dossier", "consensus", "score", "status", "live_status",
                  "outcome", "result", "result_text", "matched_id"):
            if o.get(k):
                m[k] = o[k]
    deadline = min((m["time"] for m in matches if m["time"]), default="")
    return {
        "period": str(period),
        "picks_ready": any(m.get("pick_primary") for m in matches),
        "deadline": deadline,
        "total_matches": len(matches),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "matches": matches,
    }


def same_round(matches, existing):
    """按对阵判断是不是同一期。

    不能只比 period 字段——2026-10-22 发现线上数据标着 26147，装的却是 26146 的 10-21 欧冠场次，
    标签本身就是错的。对阵比标签可靠。
    """
    old = {(m.get("home"), m.get("away")) for m in existing.get("matches", [])}
    new = {(m["home"], m["away"]) for m in matches}
    return bool(old) and old == new


def main(force=False):
    period = fetch_current_period()
    if not period:
        print("拿不到当前期号，放弃")
        return 1
    html = _get(f"https://trade.500.com/sfc/?expect={period}")
    matches, odds_ready = parse_fixtures(html)
    if len(matches) < 14:
        print(f"只解析到 {len(matches)} 场（应为 14），放弃")
        return 1

    existing = load_existing()
    same = same_round(matches, existing)
    if same and not odds_ready and not force:
        print(f"{period} 期赔率尚未开出，保持现状")
        return 0
    if same and odds_ready and not force:
        # 同期已有完整数据且已算过，不用重算
        if all(m.get("quant_factors") for m in existing.get("matches", [])):
            print(f"{period} 期已完成，跳过")
            return 0

    data = build(period, matches, existing if same else {})

    # 先落盘，再让 quant_engine 读文件算因子并回写（它的接口就是读路径→改→写路径）
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if odds_ready:
        try:
            import quant_engine
            quant_engine.run_pipeline_on_sfc(OUT)
        except Exception as e:
            print("量化失败:", type(e).__name__, e)

    with open(OUT, encoding="utf-8") as f:
        final = f.read()

    # 内容没变就不推，避免每半小时一次空提交
    if final.strip() == json.dumps(existing, ensure_ascii=False, indent=2).strip():
        print(f"{period} 期内容无变化，跳过发布")
        return 0

    publish()
    print(f"{period} 期已更新：{len(matches)} 场，赔率{'就绪' if odds_ready else '未开'}")
    return 0


def publish():
    """推 GitHub Pages + 直传阿里云（失败只告警，不影响本地文件）"""
    def run(cmd, **kw):
        try:
            r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=60, **kw)
            if r.returncode != 0:
                print(f"  ! {' '.join(cmd[:3])} -> {(r.stderr or r.stdout).strip()[:100]}")
        except Exception as e:
            print(f"  ! {' '.join(cmd[:3])} 失败: {type(e).__name__}")

    run(["git", "add", "data/sfc_matches.json"])
    run(["git", "-c", "user.name=owner", "-c", "user.email=owner@local",
         "commit", "-m", "Auto-Update: 传足赛程刷新"])
    run(["git", "push", "origin", "main"])
    run(["scp", "-o", "StrictHostKeyChecking=no", OUT,
         "aliyun:/var/www/football_live/data/sfc_matches.json"])
    run(["scp", "-o", "StrictHostKeyChecking=no", OUT,
         "aliyun:/var/www/football_live/sfc_matches.json"])


if __name__ == "__main__":
    sys.exit(main(force="--force" in sys.argv))
