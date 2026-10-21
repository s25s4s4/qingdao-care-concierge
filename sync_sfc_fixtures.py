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
HISTORY = os.path.join(HERE, "data", "sfc_history.json")
HISTORY_KEEP = 30        # 最多留 30 期
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


def update_scores():
    """从 live.500.com 完场页按 **fid** 精确取比分。

    为什么不用服务器上原来那套：它是拿 `home[:2]` 去 `html.find()`，
    「利物」先命中的是 **利物浦U19 vs 比利亚雷亚尔U19**（欧青联 0-0），
    于是把成年队 4-3 覆盖成 0-0。2026-10-22 实测就是这样，7 场全错。
    改用 500 页面自带的 `gy="赛事,主队,客队"` 与 `fid` 精确对应。
    """
    try:
        html = _get("https://live.500.com/wanchang.php")
    except Exception as e:
        _log(f"完场页抓取失败: {type(e).__name__}")
        return 0

    # fid -> (主队进球, 客队进球, 是否完场)
    by_fid = {}
    for fid, gy in re.findall(r'<tr id="a(\d+)" gy="([^"]*)"', html):
        st = html.find(f'id="a{fid}"')
        tr = html[st:html.find("</tr>", st)]
        pk = re.findall(r'class="clt[13]"\s*>([^<]*)</a>', tr)
        if len(pk) < 2 or not pk[0].strip() or not pk[1].strip():
            continue
        try:
            by_fid[fid] = (int(pk[0]), int(pk[1]), "完" in tr[:600])
        except ValueError:
            continue

    if not by_fid:
        _log("完场页没有可用比分")
        return 0

    data = load_existing()
    if not data.get("matches"):
        return 0

    changed = 0
    for m in data["matches"]:
        fid = str(m.get("fid") or "")
        got = by_fid.get(fid) if fid else None
        if not got:
            continue
        hg, ag, fin = got
        score = f"{hg}-{ag}"
        if m.get("score") == score and (not fin or m.get("status") == "已完赛"):
            continue
        m["score"] = score
        if fin:
            m["status"] = "已完赛"
            m["live_status"] = "FIN"
            outcome = "3" if hg > ag else ("1" if hg == ag else "0")
            m["outcome"] = outcome
            if outcome == str(m.get("pick_primary") or ""):
                m["result"], m["result_text"] = "HIT_PRIMARY", "首选命中"
            elif outcome == str(m.get("pick_secondary") or ""):
                m["result"], m["result_text"] = "HIT_SECONDARY", "次选命中"
            elif outcome == str(m.get("pick_upset") or ""):
                m["result"], m["result_text"] = "HIT_UPSET", "防冷命中"
            else:
                m["result"], m["result_text"] = "MISS", "未中"
        else:
            m["status"] = "进行中"
        changed += 1

    if changed:
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _log(f"比分更新 {changed} 场")
    return changed


def archive_period(old):
    """换期前把上一期存进历史，否则一切期就永久丢了。

    只留精简字段——案卷(dossier)体积大且只在当期有用。
    """
    if not old or not old.get("matches"):
        return None
    period = str(old.get("period") or "")
    if not period:
        return None

    hist = {"updated_at": "", "periods": []}
    if os.path.exists(HISTORY):
        try:
            with open(HISTORY, encoding="utf-8") as f:
                hist = json.load(f)
        except Exception:
            pass
    periods = [p for p in hist.get("periods", []) if str(p.get("period")) != period]

    s = {"total": 0, "hit_primary": 0, "hit_secondary": 0, "hit_upset": 0, "miss": 0, "pending": 0}
    ms = []
    for m in old["matches"]:
        r = str(m.get("result") or "")
        s["total"] += 1
        if r == "HIT_PRIMARY":
            s["hit_primary"] += 1
        elif r == "HIT_SECONDARY":
            s["hit_secondary"] += 1
        elif r == "HIT_UPSET":
            s["hit_upset"] += 1
        elif r == "MISS":
            s["miss"] += 1
        else:
            s["pending"] += 1
        ms.append({
            "no": m.get("no"), "league": m.get("league"), "time": m.get("time"),
            "home": m.get("home"), "away": m.get("away"),
            "score": m.get("score", ""), "outcome": m.get("outcome", ""),
            "pick_primary": m.get("pick_primary"), "pick_secondary": m.get("pick_secondary"),
            "pick_upset": m.get("pick_upset"), "result": r,
            "result_text": m.get("result_text", ""),
        })
    s["hit"] = s["hit_primary"] + s["hit_secondary"] + s["hit_upset"]

    periods.append({
        "period": period,
        "deadline": old.get("deadline", ""),
        "archived_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": s,
        "matches": ms,
    })
    periods.sort(key=lambda x: str(x.get("period")), reverse=True)
    hist["periods"] = periods[:HISTORY_KEEP]
    hist["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)
    return s


def all_finished(existing):
    """上一期是否已经全部打完。

    竞彩一期 14 场会跨两天（例如 26146 是 10-21 03:00 到 10-22 03:00）。
    只要还有一场没结束就不能换期——否则会把正在进行的这期连同已算好的选号一起冲掉，
    用户看到的就是「上一期还没打完，页面已经跳到下一期」。
    """
    ms = existing.get("matches") or []
    if not ms:
        return True
    for m in ms:
        st = str(m.get("status") or "")
        if "已完赛" in st or str(m.get("live_status") or "") == "FIN":
            continue
        return False
    return True


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
        _log("拿不到当前期号，放弃")
        return 1
    html = _get(f"https://trade.500.com/sfc/?expect={period}")
    matches, odds_ready = parse_fixtures(html)
    if len(matches) < 14:
        _log(f"只解析到 {len(matches)} 场（应为 14），放弃")
        return 1

    update_scores()          # 先把比分刷新（按 fid 精确匹配）
    existing = load_existing()

    # 换期闸门：上一期没打完就不动
    if not all_finished(existing) and not force:
        left = sum(1 for m in existing.get("matches", [])
                   if "已完赛" not in str(m.get("status") or ""))
        _log(f"上一期（{existing.get('period')}）还有 {left} 场未结束，暂不换到 {period} 期")
        return 0

    same = same_round(matches, existing)
    if not same:
        _s = archive_period(existing)
        if _s:
            _log(f"上一期 {existing.get('period')} 已归档：{_s['hit']} 中 / {_s['miss']} 失")

    if same and not odds_ready and not force:
        _log(f"{period} 期赔率尚未开出，保持现状")
        return 0
    if same and odds_ready and not force:
        # 同期已有完整数据且已算过，不用重算
        if all(m.get("quant_factors") for m in existing.get("matches", [])):
            _log(f"{period} 期已完成，跳过")
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
            _log(f"量化失败: {type(e).__name__} {e}")

    with open(OUT, encoding="utf-8") as f:
        final = f.read()

    # 内容没变就不推，避免每半小时一次空提交
    if final.strip() == json.dumps(existing, ensure_ascii=False, indent=2).strip():
        _log(f"{period} 期内容无变化，跳过发布")
        return 0

    publish()
    _log(f"{period} 期已更新：{len(matches)} 场，赔率{'就绪' if odds_ready else '未开'}")
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

    run(["git", "add", "data/sfc_matches.json", "data/sfc_history.json"])
    run(["git", "-c", "user.name=owner", "-c", "user.email=owner@local",
         "commit", "-m", "Auto-Update: 传足赛程刷新"])
    run(["git", "push", "origin", "main"])
    run(["scp", "-o", "StrictHostKeyChecking=no", OUT,
         "aliyun:/var/www/football_live/data/sfc_matches.json"])
    run(["scp", "-o", "StrictHostKeyChecking=no", OUT,
         "aliyun:/var/www/football_live/sfc_matches.json"])


def _log(msg):
    """pythonw 没有控制台，输出落文件方便事后查"""
    try:
        with open(os.path.join(HERE, "sfc_sync.log"), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass
    print(msg)


if __name__ == "__main__":
    try:
        code = main(force="--force" in sys.argv)
    except Exception as exc:
        _log(f"异常 {type(exc).__name__}: {exc}")
        raise SystemExit(1)
    sys.exit(code)
