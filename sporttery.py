"""中国竞彩官方 SP 源（sporttery.cn 公开接口）。
失败必须显式返回 None，由调用方降级到 500.com，绝不用旧值冒充。
"""
import json
import urllib.request

URL = ("https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry"
       "?poolCode=hhad,had&channel=c")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0 Safari/537.36",
    "Referer": "https://www.sporttery.cn/",
    "Origin": "https://www.sporttery.cn",
    "Accept": "application/json, text/plain, */*",
}


def fetch(timeout=10):
    """返回 {(home, away, 'MM-DD'): {had, hhad, updated}}；异常返回 None。"""
    try:
        req = urllib.request.Request(URL, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    value = (payload or {}).get("value") or {}
    updated = value.get("lastUpdateTime") or ""
    out = {}
    for day in value.get("matchInfoList") or []:
        business = str(day.get("businessDate") or "")
        for item in day.get("subMatchList") or []:
            home = str(item.get("homeTeamAbbName") or "").strip()
            away = str(item.get("awayTeamAbbName") or "").strip()
            if not home or not away:
                continue
            date = business[5:10] if len(business) >= 10 else ""
            had = item.get("had") or {}
            hhad = item.get("hhad") or {}
            record = {"had": None, "hhad": None, "updated": updated, "matchId": item.get("matchId")}
            if had.get("h") and had.get("d") and had.get("a"):
                record["had"] = [str(had["h"]), str(had["d"]), str(had["a"])]
            if hhad.get("h") and hhad.get("d") and hhad.get("a"):
                record["hhad"] = [str(hhad["h"]), str(hhad["d"]), str(hhad["a"])]
                record["goalLine"] = str(hhad.get("goalLine", "0"))
            if record["had"] or record["hhad"]:
                out[(home, away, date)] = record
    return out or None


def apply(matches, official):
    """把官方 SP 合并进本地数据。返回 (更新数, 冲突数)。"""
    if not official:
        return 0, 0
    updated = conflicts = 0
    for m in matches:
        date = str(m.get("time", ""))[:5]
        # 竞彩 businessDate 是售卖日，凌晨开球会跨日；先按日期匹配，再按双方兜底
        rec = official.get((m.get("home"), m.get("away"), date))
        if not rec:
            rec = next((v for (h, a, _d), v in official.items()
                        if h == m.get("home") and a == m.get("away")), None)
        if not rec:
            continue
        target = rec["had"] or rec["hhad"]
        local = m.get("odds")
        if rec["had"]:
            m["odds_official"] = rec["had"]
            m["official_market"] = "had"
        else:
            m["odds_official"] = rec["hhad"]
            m["official_market"] = "hhad"
            m["official_goal_line"] = rec.get("goalLine")
        if local and target and [str(x) for x in local] != target:
            m["odds_conflict"] = {"local": local, "official": target, "at": rec["updated"]}
            conflicts += 1
        # 官方优先：仅在双方盘口类型一致时替换，避免让球盘覆盖胜平负盘
        same_market = (m.get("is_only_rq") and rec["hhad"]) or (not m.get("is_only_rq") and rec["had"])
        if same_market:
            m["odds"] = target
            m["odds_source"] = "sporttery_official"
            updated += 1
        else:
            m.setdefault("odds_source", m.get("source_name", "500.com"))
    return updated, conflicts
