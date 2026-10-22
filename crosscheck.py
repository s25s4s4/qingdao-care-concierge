"""第二比分源（FotMob）交叉校验：只报冲突，不静默改分。
免费、无需 key；覆盖主流联赛。名称通过别名表 + 归一化匹配。
"""
import json
import os
import unicodedata
import urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ALIAS_FILE = os.path.join(BASE, "data", "team_aliases.json")
HEALTH_FILE = os.path.join(BASE, "data", "source_health.json")

SUFFIX = (" fc", " cf", " sc", " ac", " afc", " united", " city", " club")


def _norm(name):
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold().strip()
    for suffix in SUFFIX:
        if text.endswith(suffix) and len(text) > len(suffix) + 2:
            text = text[: -len(suffix)]
    return "".join(c for c in text if c.isalnum())


def _aliases():
    try:
        with open(ALIAS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def fetch_results(day):
    """day: 'YYYY-MM-DD'。返回 {(home_norm, away_norm): {'score','finished','started'}}"""
    stamp = day.replace("-", "")
    req = urllib.request.Request(
        "https://www.fotmob.com/api/data/matches?date=" + stamp,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    out = {}
    for league in payload.get("leagues", []):
        for match in league.get("matches", []):
            status = match.get("status", {}) or {}
            out[(_norm(match.get("home", {}).get("name")), _norm(match.get("away", {}).get("name")))] = {
                "score": status.get("scoreStr"), "finished": bool(status.get("finished")),
                "started": bool(status.get("started")), "league": league.get("name")}
    return out


def _year_for(md):
    """'MM-DD' -> 所属年份。跨年时取距今天最近的一年（12 月 vs 1 月不搞错）。"""
    now = datetime.now()
    try:
        dt = datetime.strptime(f"{now.year}-{md}", "%Y-%m-%d").date()
    except ValueError:
        return now.year
    if (dt - now.date()).days > 200:
        return now.year - 1
    if (now.date() - dt).days > 200:
        return now.year + 1
    return now.year


def _prev(day):
    """'MM-DD' -> 前一天的 'MM-DD'（北京时间凌晨开球对应欧洲前一天）。"""
    from datetime import timedelta
    try:
        dt = datetime.strptime(f"{_year_for(day)}-{day}", "%Y-%m-%d").date() - timedelta(days=1)
        return dt.strftime("%m-%d")
    except ValueError:
        return day


def crosscheck(matches, now=None):
    """对已完赛/进行中的比赛做双源比对，冲突写入 source_health.json。"""
    aliases = _aliases()
    base_days = {str(m.get("time", ""))[:5] for m in matches if m.get("time")}
    # 北京时间凌晨开球对应欧洲前一天，需同时查前一天
    days = sorted(base_days | {_prev(d) for d in base_days})
    report = {"checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "source": "fotmob",
              "days": {}, "conflicts": [], "unmatched": 0, "matched": 0, "errors": []}
    cache = {}
    for day in days:
        full = f"{_year_for(day)}-{day}"
        try:
            cache[day] = fetch_results(full)
            report["days"][day] = len(cache[day])
        except Exception as exc:
            report["errors"].append({day: type(exc).__name__})
    for m in matches:
        day = str(m.get("time", ""))[:5]
        home = aliases.get(m.get("home"), m.get("home"))
        away = aliases.get(m.get("away"), m.get("away"))
        hit = None
        for candidate in (day, _prev(day)):
            source = cache.get(candidate)
            if source:
                hit = source.get((_norm(home), _norm(away)))
                if hit:
                    day = candidate
                    break
        if not hit:
            report["unmatched"] += 1
            continue
        report["matched"] += 1
        # 两边都去掉所有空格再比：live.500 存 '2-1'，FotMob 回 '2 - 1'，
        # 早年直接 replace('-',' - ') 导致两边永远不相等、场场假冲突（2026-10-22 修复）。
        local = str(m.get("score") or "").replace(" ", "")
        remote = str(hit.get("score") or "").replace(" ", "")
        m["crosscheck"] = {"source": "fotmob", "score": remote, "finished": hit.get("finished")}
        if hit.get("finished") and remote and local and remote != local:
            report["conflicts"].append({"code": m.get("code"), "home": m.get("home"), "away": m.get("away"),
                                        "local": local, "fotmob": remote, "day": day})
            m["score_conflict"] = {"local": local, "fotmob": remote, "at": report["checked_at"]}
    with open(HEALTH_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report
