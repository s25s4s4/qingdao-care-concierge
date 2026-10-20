# -*- coding: utf-8 -*-
"""用本机 Edge 无头渲染 Understat，拿五大联赛的当季战绩 + xG。

为什么要这么绕：
  * fbref / sofascore / thesportsdb 对纯 HTTP 请求直接 403；
  * understat 对纯 HTTP 返回 200，但数据由 js/league.min.js 异步渲染，HTML 里抓不到；
  * 用 --headless --dump-dom 让真浏览器跑完 JS，DOM 里就有完整表格。

代价：每个联赛约 10-15 秒，5 个联赛近 1 分钟，所以只在数据过期时跑，不进每分钟流水线。

产物：data/understat_teams.json
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "understat_teams.json")
ALIAS = os.path.join(HERE, "data", "team_aliases.json")

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
LEAGUES = [
    ("EPL", "英超"),
    ("La_liga", "西甲"),
    ("Bundesliga", "德甲"),
    ("Serie_A", "意甲"),
    ("Ligue_1", "法甲"),
]
SEASON = str(datetime.now().year)      # understat 用赛季起始年，2026 表示 2026/27


# 别名表里用的是带重音/意译的官方名（Atlético Madrid / Bayern München），
# understat 用英文常用名（Atletico Madrid / Bayern Munich），这里补一层同义词
EXTRA_EN = {
    "bayern munich": "拜仁",
    "fc cologne": "科隆",
    "rasenballsport leipzig": "莱红牛",
    "borussia m gladbach": "门兴",
    "atletico madrid": "马竞",
    "deportivo la coruna": "拉科",
    "malaga": "马拉加",
}


def _norm(s):
    s = s.lower()
    s = unicodedata.normalize("NFKD", s)          # Atlético -> Atletico, Köln -> Koln
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[-.'’&/]", " ", s)      # 连字符/点号先变空格，否则 "Saint-Germain" 会粘成 "saintgermain"
    s = re.sub(r"[^a-z0-9 ]", "", s)
    for w in (" fc", " afc", " cf", " sc", " ac", " town", " city", " united",
              " utd", " albion", " hotspur", " wanderers", " rovers", " athletic",
              " & hove", " club", " de", " calcio"):
        s = s.replace(w, "")
    return re.sub(r"\s+", " ", s).strip()


def build_matcher():
    """中文 -> 英文 的别名表反过来，再做归一化索引"""
    cn2en = {}
    if os.path.exists(ALIAS):
        try:
            with open(ALIAS, encoding="utf-8") as f:
                cn2en = json.load(f)
        except Exception:
            cn2en = {}
    en2cn = {}
    for cn, en in cn2en.items():
        en2cn[_norm(en)] = cn
    return cn2en, en2cn


def match_cn(en_name, en2cn):
    """先精确归一化匹配，再退化为前缀/包含匹配"""
    n = _norm(en_name)
    if n in EXTRA_EN:
        return EXTRA_EN[n]
    if n in en2cn:
        return en2cn[n]
    for k, cn in en2cn.items():
        if not k:
            continue
        if n.startswith(k) or k.startswith(n):
            return cn
    for k, cn in en2cn.items():
        if len(k) >= 4 and (k in n or n in k):
            return cn
    return None


def fetch_league(code, timeout=60):
    url = f"https://understat.com/league/{code}/{SEASON}"
    # 每次用独立的 user-data-dir：共用同一个 profile 时，第二个实例会拿到锁、
    # 直接返回空 DOM（表现为"跑完但没有数据"，很难查）。
    udd = tempfile.mkdtemp(prefix="edge_us_")
    cmd = [EDGE, "--headless=new", "--disable-gpu", "--no-sandbox",
           f"--user-data-dir={udd}",
           "--virtual-time-budget=12000", "--dump-dom", url]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        html = r.stdout.decode("utf-8", errors="ignore")
    except Exception as e:
        return None, f"{type(e).__name__}"
    finally:
        shutil.rmtree(udd, ignore_errors=True)
    if "league-chemp" not in html and "xG" not in html:
        return None, "no-table"

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    out = []
    for r_ in rows:
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", r_, re.S)]
        # 球队行：cells[2] 是数字（场次）；球员行 cells[2] 是队名
        if len(cells) < 12 or not cells[0].isdigit() or not cells[2].isdigit():
            continue
        try:
            # xG / xGA / xPTS 三列是「数值+差值」挤在一个单元格里，如 "16.64-2.36"
            def _num(x):
                m = re.match(r"-?\d+(?:\.\d+)?", x)
                return float(m.group()) if m else None
            out.append({
                "en": cells[1],
                "gp": int(cells[2]), "w": int(cells[3]), "d": int(cells[4]), "l": int(cells[5]),
                "gf": int(cells[6]), "ga": int(cells[7]), "pts": int(cells[8]),
                "xg": _num(cells[9]), "xga": _num(cells[10]), "xpts": _num(cells[11]),
            })
        except Exception:
            continue
    return out, None


def refresh(verbose=True):
    cn2en, en2cn = build_matcher()
    data = {"updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "season": SEASON, "leagues": {}}
    for code, cn in LEAGUES:
        t0 = time.time()
        teams, err = fetch_league(code)
        if not teams:
            if verbose:
                print(f"  {cn:<4} 失败: {err}")
            continue
        for t in teams:
            t["cn"] = match_cn(t["en"], en2cn)
        hit = sum(1 for t in teams if t["cn"])
        data["leagues"][cn] = teams
        if verbose:
            print(f"  {cn:<4} {len(teams):>2} 队  中文匹配 {hit:>2}  {time.time() - t0:.1f}s")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if verbose:
        print(f"写入 {OUT}")
    return data


def load():
    if not os.path.exists(OUT):
        return None
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


LOCK = os.path.join(HERE, "data", ".understat.lock")


def is_locked(max_minutes=10):
    """是否有刷新正在跑（防止失败时每分钟拉起一个 2 分钟的浏览器进程）"""
    if not os.path.exists(LOCK):
        return False
    age = time.time() - os.path.getmtime(LOCK)
    if age > max_minutes * 60:
        try:
            os.remove(LOCK)
        except Exception:
            pass
        return False
    return True


def _touch_lock():
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    with open(LOCK, "w") as f:
        f.write(str(time.time()))


def stale(hours=6):
    if not os.path.exists(OUT):
        return True
    return (time.time() - os.path.getmtime(OUT)) > hours * 3600


def team_season(cn_name, league_cn, data=None):
    """按中文队名取当季数据"""
    data = data or load()
    if not data:
        return None
    for t in data.get("leagues", {}).get(league_cn, []):
        if t.get("cn") == cn_name:
            return t
    return None


if __name__ == "__main__":
    if "--check" in sys.argv:
        d = load()
        if not d:
            print("尚未抓取")
        else:
            print(f"抓取于 {d['updated_at']}  赛季 {d['season']}")
            for lg, ts in d.get("leagues", {}).items():
                print(f"  {lg}: {len(ts)} 队，中文匹配 {sum(1 for t in ts if t.get('cn'))}")
            for t in d.get("leagues", {}).get("英超", [])[:6]:
                print("   ", t["cn"] or "(未匹配)", t["en"], t["gp"], f'{t["w"]}-{t["d"]}-{t["l"]}',
                      f'{t["gf"]}:{t["ga"]}', "xG", t["xg"], "xGA", t["xga"])
        raise SystemExit(0)

    if is_locked():
        print("已有刷新在跑，跳过")
        raise SystemExit(0)
    _touch_lock()
    try:
        print("抓取 Understat 五大联赛…")
        refresh()
    finally:
        try:
            os.remove(LOCK)
        except Exception:
            pass
