# -*- coding: utf-8 -*-
"""传足（胜负彩 14 场）赛程刷新与完场自动打戳引擎。

核心职责：
  1. 从 500.com 抓取传足 14 场赛程与官方平均欧赔，交由 quant_engine 推演首选/次选/防冷选号；
  2. 从 `live.500.com/zucai.php?e=<期号>` + `live.500.com/` 按 fid 精确同步实时比分与完场赛果，
     自动计算 HIT_PRIMARY / HIT_SECONDARY / HIT_UPSET / MISS 命中印章；
  3. 任何比分或状态变更均立即同步至 GitHub 与阿里云服务器（含 sfc_matches.json 与 sfc_history.json）；
  4. 换期时完整归档上一期全量卡片字段（并附带于 previous_period），确保前端可随时切换查看上期打戳复盘与新期选号。
"""
import copy
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "sfc_matches.json")
HISTORY = os.path.join(HERE, "data", "sfc_history.json")
HISTORY_KEEP = 30        # 最多留 30 期
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0 Safari/537.36"

# 直连 opener（绕过本机系统代理，防止国内 500.com 走海外代理节点触发 SSL 证书错误或断流）
_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_UNVERIFIED_SSL = ssl._create_unverified_context()


def _get(url, timeout=15, referer="https://trade.500.com/"):
    headers = {"User-Agent": UA, "Referer": referer}
    last_err = None
    candidates = [url]
    if url.startswith("https://"):
        candidates.append(url.replace("https://", "http://", 1))
    for candidate_url in candidates:
        for use_direct in (True, False):
            try:
                req = urllib.request.Request(candidate_url, headers=headers)
                if use_direct:
                    with _DIRECT_OPENER.open(req, timeout=timeout) as r:
                        return r.read().decode("gbk", errors="ignore")
                else:
                    with urllib.request.urlopen(req, timeout=timeout, context=_UNVERIFIED_SSL) as r:
                        return r.read().decode("gbk", errors="ignore")
            except Exception as e:
                last_err = e
    raise last_err


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


def fetch_avg_odds(fid):
    """从 odds.500.com 欧赔页提取平均欧赔（avwinc2 / avdrawc2 / avlostc2）。
    加入重试与短暂间隔，防止连续抓 14 场时被 500.com 限流断连。"""
    if not fid:
        return []
    url = f"https://odds.500.com/fenxi/ouzhi-{fid}.shtml"
    for attempt in range(3):
        try:
            if attempt > 0:
                time.sleep(0.4 * attempt)
            h = _get(url, timeout=12, referer="https://trade.500.com/sfc/")
            out = []
            for key in ("avwinc2", "avdrawc2", "avlostc2"):
                m = re.search(rf'id="{key}"[^>]*>\s*([0-9]+\.[0-9]+)', h)
                if not m:
                    out = []
                    break
                out.append(m.group(1))
            if len(out) == 3:
                time.sleep(0.15)
                return out
        except Exception:
            continue
    return []


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
    res = {
        "period": str(period),
        "picks_ready": any(m.get("pick_primary") for m in matches),
        "deadline": deadline,
        "total_matches": len(matches),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "matches": matches,
    }
    if existing.get("previous_period"):
        res["previous_period"] = existing["previous_period"]
    return res


def _parse_live_rows(html, by_fid):
    """从 500 比分页 HTML 中提取 id="a<fid>" status="N" 与主客场比分"""
    for m in re.finditer(r"<tr([^>]*)>(.*?)</tr>", html, re.S):
        attrs, body = m.group(1), m.group(2)
        f = re.search(r'id="a(\d+)"', attrs)
        st = re.search(r'status="([^"]*)"', attrs)
        if not (f and st):
            continue
        fid, status = f.group(1), st.group(1)
        pk = re.findall(r'class="clt[13]"\s*>([^<]*)</a>', body)
        if len(pk) < 2 or not pk[0].strip() or not pk[1].strip():
            continue
        try:
            hg, ag = int(pk[0].strip()), int(pk[1].strip())
        except ValueError:
            continue
        # 若已有完场状态 "4"，不被旧状态覆盖
        prev = by_fid.get(fid)
        if prev and prev[2] == "4" and status != "4":
            continue
        by_fid[fid] = (hg, ag, status)


def _apply_scores_to_matches(matches, by_fid):
    """将 by_fid 中的比分与完场状态应用到 matches 列表，并自动盖上命中印章"""
    changed = 0
    for m in matches:
        got = by_fid.get(str(m.get("fid") or ""))
        if not got:
            continue
        hg, ag, status = got
        score = f"{hg}-{ag}"
        fin = status == "4"
        if fin:
            new_status, new_live = "已完赛", "FIN"
        elif status in ("1", "2", "3"):
            new_status, new_live = "进行中", "LIVE"
        else:
            continue          # 0=未开赛，不覆盖

        outcome = ""
        new_res, new_res_text = m.get("result"), m.get("result_text", "")
        if fin:
            outcome = "3" if hg > ag else ("1" if hg == ag else "0")
            if outcome == str(m.get("pick_primary") or ""):
                new_res, new_res_text = "HIT_PRIMARY", "首选命中"
            elif outcome == str(m.get("pick_secondary") or ""):
                new_res, new_res_text = "HIT_SECONDARY", "次选命中"
            elif outcome == str(m.get("pick_upset") or ""):
                new_res, new_res_text = "HIT_UPSET", "防冷命中"
            else:
                new_res, new_res_text = "MISS", "未中"

        if (m.get("score") == score and m.get("status") == new_status
                and m.get("result") == new_res and m.get("outcome") == outcome):
            continue

        m["score"] = score
        m["status"] = new_status
        m["live_status"] = new_live
        if fin:
            m["outcome"] = outcome
            m["result"] = new_res
            m["result_text"] = new_res_text
        changed += 1
    return changed


def update_scores():
    """从 500 足彩专属比分页 (`zucai.php?e=<期号>`) + 竞彩首页 (`live.500.com/`) 按 fid 精确取比分。

    为什么必须优先抓 `zucai.php?e=<期号>`：
      1. `live.500.com/` 默认只展示竞彩赛事，而传足 14 场经常包含竞彩未开售的欧协联/意乙/法乙等场次
         （例如 26147 期第 1、11、13、14 场），只抓首页会导致这几场永远卡在“未开赛”；
      2. 次日早上 10:00 后 `live.500.com/` 会切到新一天赛程，昨晚完场赛事全部滚出首页；
      3. `zucai.php?e=<期号>` 按期号永久保留该期全部 14 场传足对阵的实时与完场比分，HTML 结构完全一致。
    """
    data = load_existing()
    if not data.get("matches"):
        return 0

    existing_period = str(data.get("period") or "")
    prev_period = str((data.get("previous_period") or {}).get("period") or "")

    urls = []
    if existing_period:
        urls.append(f"https://live.500.com/zucai.php?e={existing_period}")
    if prev_period and prev_period != existing_period:
        urls.append(f"https://live.500.com/zucai.php?e={prev_period}")
    urls.extend([
        "https://live.500.com/zucai.php",
        "https://live.500.com/",
    ])

    by_fid = {}
    for u in urls:
        try:
            html = _get(u, referer="https://live.500.com/")
            _parse_live_rows(html, by_fid)
        except Exception as e:
            _log(f"比分页抓取异常 ({u}): {type(e).__name__}")

    if not by_fid:
        _log("比分页暂无在售场次（非错误）")
        return 0

    changed = _apply_scores_to_matches(data["matches"], by_fid)
    if data.get("previous_period") and data["previous_period"].get("matches"):
        changed += _apply_scores_to_matches(data["previous_period"]["matches"], by_fid)

    if changed:
        data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _log(f"比分更新 {changed} 场")

    # 若当期或上一期已全部完赛，同步写入/更新 sfc_history.json，确保历史复盘与打戳实时就绪
    if all_finished(data):
        archive_period(data)
    if data.get("previous_period") and all_finished(data["previous_period"]):
        archive_period(data["previous_period"])

    return changed


def _summarize_matches(matches):
    s = {"total": 0, "hit_primary": 0, "hit_secondary": 0, "hit_upset": 0, "miss": 0, "pending": 0}
    for m in matches:
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
    s["hit"] = s["hit_primary"] + s["hit_secondary"] + s["hit_upset"]
    return s


def archive_period(old):
    """将已完成（或换期前）的期次存入 sfc_history.json，完整保留卡片渲染所需字段与打戳结果。"""
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

    s = _summarize_matches(old["matches"])
    ms = []
    for m in old["matches"]:
        ms.append({
            "no": m.get("no"),
            "league": m.get("league"),
            "league_color": m.get("league_color", "#6F00DD"),
            "time": m.get("time"),
            "home": m.get("home"),
            "home_rank": m.get("home_rank", ""),
            "away": m.get("away"),
            "away_rank": m.get("away_rank", ""),
            "fid": m.get("fid", ""),
            "status": m.get("status", "已完赛"),
            "live_status": m.get("live_status", "FIN"),
            "odds": m.get("odds", []),
            "score": m.get("score", ""),
            "outcome": m.get("outcome", ""),
            "pick_primary": m.get("pick_primary"),
            "pick_secondary": m.get("pick_secondary"),
            "pick_upset": m.get("pick_upset"),
            "pick_desc": m.get("pick_desc", ""),
            "result": m.get("result"),
            "result_text": m.get("result_text", ""),
            "quant_factors": m.get("quant_factors", {}),
            "consensus": m.get("consensus", ""),
            "dossier": m.get("dossier", {}),
        })

    periods.append({
        "period": period,
        "picks_ready": old.get("picks_ready", True),
        "deadline": old.get("deadline", ""),
        "total_matches": len(ms),
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
    """上一期是否已经全部打完。"""
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
    """按对阵判断是不是同一期。"""
    old = {(m.get("home"), m.get("away")) for m in existing.get("matches", [])}
    new = {(m["home"], m["away"]) for m in matches}
    return bool(old) and old == new


def main(force=False):
    # 1. 无论是否换期，先把已有期次的实时比分与完场命中戳刷新
    score_changed = update_scores()
    existing = load_existing()

    period = fetch_current_period()
    if not period:
        if score_changed:
            publish()
        _log("拿不到当前期号，放弃")
        return 1

    html = _get(f"https://trade.500.com/sfc/?expect={period}")
    matches, odds_ready = parse_fixtures(html)
    if len(matches) < 14:
        if score_changed:
            publish()
        _log(f"只解析到 {len(matches)} 场（应为 14），放弃")
        return 1

    same = same_round(matches, existing)

    # 2. 同期且选号已完成：若刚才 update_scores() 有新比分/新盖章，必须立即 publish() 推送线上！
    if same and not force:
        _ex = existing.get("matches") or []
        if _ex and all((m.get("quant_factors") and m.get("pick_primary")) for m in _ex):
            if score_changed:
                publish()
                _log(f"{period} 期比分/命中戳已同步发布（更新 {score_changed} 场）")
            else:
                _log(f"{period} 期已完成，跳过")
            return 0

    # 3. 换期闸门：只有当上一期 14 场全部完赛后才允许切换到下一期
    if not same and not all_finished(existing) and not force:
        if score_changed:
            publish()
            _log(f"上一期（{existing.get('period')}）比分已同步发布（更新 {score_changed} 场）")
        left = sum(1 for m in existing.get("matches", [])
                   if "已完赛" not in str(m.get("status") or ""))
        _log(f"上一期（{existing.get('period')}）还有 {left} 场未结束，暂不换到 {period} 期")
        return 0

    # 4. 补抓平均欧赔（已有赔率的场次不重复抓）
    if not odds_ready:
        old_odds = {}
        if same:
            for m in existing.get("matches", []):
                if m.get("odds") and len(m["odds"]) == 3:
                    old_odds[(m.get("home"), m.get("away"))] = m["odds"]
        got = 0
        for m in matches:
            cached = old_odds.get((m["home"], m["away"]))
            if cached:
                m["odds"] = cached
                got += 1
                continue
            o = fetch_avg_odds(m.get("fid"))
            if o:
                m["odds"] = o
                got += 1
        # 换期时要求新一期全部 14 场欧赔齐全才覆盖（避免半成品无选号冲掉上一期完赛红单榜）
        odds_ready = (got == len(matches)) if not same else (got > 0)
        _log(f"欧赔补抓：{got}/{len(matches)} 场")

    if not odds_ready and not force:
        if score_changed:
            publish()
            _log(f"上一期（{existing.get('period')}）完场打戳已同步发布；新一期 {period} 欧赔未齐暂缓换期")
        else:
            _log(f"{period} 期赔率尚未全齐，保持现状")
        return 0

    prev_snapshot = None
    if not same and existing.get("matches"):
        _s = archive_period(existing)
        if _s:
            _log(f"上一期 {existing.get('period')} 已归档：{_s['hit']} 中 / {_s['miss']} 失")
        prev_snapshot = copy.deepcopy(existing)
        prev_snapshot.pop("previous_period", None)
        prev_snapshot["summary"] = _s or _summarize_matches(existing.get("matches", []))

    before_str = json.dumps(existing, ensure_ascii=False, indent=2).strip()
    data = build(period, matches, existing if same else {})
    if prev_snapshot:
        data["previous_period"] = prev_snapshot

    # 先落盘，再让 quant_engine 读文件算因子并回写
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if odds_ready:
        try:
            import quant_engine
            quant_engine.run_pipeline_on_sfc(OUT)
            with open(OUT, encoding="utf-8") as f:
                _d = json.load(f)
            _d["picks_ready"] = any(m.get("pick_primary") for m in _d.get("matches", []))
            if prev_snapshot:
                _d["previous_period"] = prev_snapshot
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(_d, f, ensure_ascii=False, indent=2)
        except Exception as e:
            _log(f"量化失败: {type(e).__name__} {e}")

    # 换期或重算后，再跑一次 update_scores 以防新期已有开赛/完场场次
    update_scores()

    with open(OUT, encoding="utf-8") as f:
        final = f.read()

    if not score_changed and final.strip() == before_str:
        _log(f"{period} 期内容无变化，跳过发布")
        return 0

    publish()
    _log(f"{period} 期已更新并发布：{len(matches)} 场，赔率{'就绪' if odds_ready else '未开'}")
    return 0


def publish():
    """推 GitHub Pages + 直传阿里云（同时同步 sfc_matches.json 与 sfc_history.json）"""
    def run(cmd, **kw):
        try:
            r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=60, **kw)
            if r.returncode != 0:
                print(f"  ! {' '.join(cmd[:3])} -> {(r.stderr or r.stdout).strip()[:100]}")
        except Exception as e:
            print(f"  ! {' '.join(cmd[:3])} 失败: {type(e).__name__}")

    run(["git", "add", "data/sfc_matches.json", "data/sfc_history.json"])
    run(["git", "-c", "user.name=owner", "-c", "user.email=owner@local",
         "commit", "-m", "Auto-Update: 传足赛程与完场打戳刷新"])
    run(["git", "push", "origin", "main"])
    run(["scp", "-o", "StrictHostKeyChecking=no", OUT,
         "aliyun:/var/www/football_live/data/sfc_matches.json"])
    run(["scp", "-o", "StrictHostKeyChecking=no", OUT,
         "aliyun:/var/www/football_live/sfc_matches.json"])
    if os.path.exists(HISTORY):
        run(["scp", "-o", "StrictHostKeyChecking=no", HISTORY,
             "aliyun:/var/www/football_live/data/sfc_history.json"])
        run(["scp", "-o", "StrictHostKeyChecking=no", HISTORY,
             "aliyun:/var/www/football_live/sfc_history.json"])


def _log(msg):
    """pythonw 没有控制台，输出落文件方便事后查"""
    try:
        with open(os.path.join(HERE, "sfc_sync.log"), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception as e:
        pass
    print(msg)


if __name__ == "__main__":
    try:
        code = main(force="--force" in sys.argv)
    except Exception as exc:
        _log(f"异常 {type(exc).__name__}: {exc}")
        raise SystemExit(1)
    sys.exit(code)
