import urllib.request
import re
import json
import os
import subprocess
from datetime import datetime

MATCHES_FILE = r"E:\euro_intel_web\data\official_matches.json"
MATCHES_34_FALLBACK = r"E:\euro_intel_web\data\matches_34.json"
WEB_DIR = r"E:\euro_intel_web"

def calculate_result(tip, score):
    if not score or "-" not in score:
        return "PENDING"
    try:
        parts = score.replace(" ", "").split("-")
        h, a = int(parts[0]), int(parts[1])
    except:
        return "PENDING"
        
    t = tip.lower()
    total = h + a
    
    # 严格根据赛前建议判定
    if "主胜" in tip:
        if h > a: return "HIT"
    if "客胜" in tip:
        if a > h: return "HIT"
    if "主不败" in tip:
        if h >= a: return "HIT"
    if "客不败" in tip:
        if a >= h: return "HIT"
    if "平" in tip and "客不败" not in tip and "主不败" not in tip:
        if h == a: return "HIT"
    if "进球数3+" in tip or "大球" in tip:
        if total >= 3: return "HIT"
    if "双方进球" in tip:
        if h > 0 and a > 0: return "HIT"
    if "让胜" in tip:
        if h - a >= 2: return "HIT"
    if "让负" in tip:
        if a - h >= 1 or a == h: return "HIT"
        
    return "MISS"

def generate_tactical_dossier(home, away, league, odds):
    try:
        sp_h = float(odds[0]) if odds[0] != '-' else 2.5
        sp_d = float(odds[1]) if odds[1] != '-' else 3.2
        sp_a = float(odds[2]) if odds[2] != '-' else 2.8
    except:
        sp_h, sp_d, sp_a = 2.0, 3.2, 3.0

    if sp_h < 1.55:
        tip = "主胜"
        consensus = f"主胜优势 ({int(85 - sp_h*5)}%)"
        ratio = int(85 - sp_h*5)
        status = "稳胆候选"
        analysis = f"{home}主场硬实力与深度占优，机构初盘给予坚实防范，攻防两端压制力强，首选主胜。"
    elif sp_a < 1.65:
        tip = "客胜"
        consensus = f"客胜优势 ({int(84 - sp_a*5)}%)"
        ratio = int(84 - sp_a*5)
        status = "客战正路"
        analysis = f"{away}客战战意坚决，前场反击纵深穿透力显著，{home}近期后防失球偏多，看好客胜正路。"
    elif sp_h < sp_a:
        tip = "主不败/首选主胜"
        consensus = f"主不败 ({int(75 - sp_h*3)}%)"
        ratio = int(75 - sp_h*3)
        status = "焦点对决"
        analysis = f"{home}坐拥主场地利，过往交锋球风有所克制，客队近期客战表现平平，主不败防平首选。"
    else:
        tip = "客不败/双选平负"
        consensus = f"客不败 ({int(74 - sp_a*3)}%)"
        ratio = int(74 - sp_a*3)
        status = "焦点对决"
        analysis = f"{away}整体战术纪律性更严明，防守韧性较强；{home}攻坚效率偶有波动，谨防客队抢分。"

    return status, tip, consensus, ratio, analysis

def fetch_official_lottery_pool():
    """从官方排期池获取当前所有开售/历史场次"""
    url = "https://trade.500.com/jczq/"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    pool_fixtures = []
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode('gbk', errors='ignore')
            matches = re.findall(
                r'<tr class="bet-tb-tr([^"]*)"[^>]*data-fixtureid="([^"]*)"[^>]*data-homesxname="([^"]*)"\s+data-awaysxname="([^"]*)"[^>]*data-matchdate="([^"]*)"\s+data-matchtime="([^"]*)"[^>]*data-rangqiu="([^"]*)"\s+data-simpleleague="([^"]*)"[^>]*data-matchnum="([^"]*)"[^>]*data-isend="([^"]*)"',
                html
            )
            for m in matches:
                cls, fid, home, away, mdate, mtime, rang, league, code, isend = m
                pos = html.find(f'data-fixtureid="{fid}"')
                sps = ["-", "-", "-"]
                if pos != -1:
                    end_pos = html.find('</tr>', pos)
                    tr_chunk = html[pos:end_pos]
                    found_sps = re.findall(r'data-type="nspf"[^>]*data-sp="([^"]*)"', tr_chunk)
                    if not found_sps:
                        found_sps = re.findall(r'data-type="spf"[^>]*data-sp="([^"]*)"', tr_chunk)
                    if len(found_sps) >= 3:
                        sps = found_sps[:3]

                pool_fixtures.append({
                    "code": code.strip(),
                    "league": league.strip(),
                    "home": home.strip(),
                    "away": away.strip(),
                    "date": mdate.strip(),
                    "time": f"{mdate[5:]} {mtime.strip()}",
                    "odds": sps,
                    "rang": rang.strip(),
                    "is_end": isend.strip()
                })
    except Exception as e:
        print(f"[{datetime.now()}] Error fetching official lottery pool: {e}")
    return pool_fixtures

def fetch_live_scores():
    """从比分网获取真实完场赛果"""
    url = "https://live.500.com/"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    live_map = {}
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode('gbk', errors='ignore')
            all_trs = re.findall(r'<tr[^>]*>.*?</tr>', html, re.DOTALL)
            for tr in all_trs:
                code_m = re.search(r'(周[一二三四五六日]\d{3})', tr)
                if code_m:
                    code = code_m.group(1)
                    score_m = re.search(r'class="red">([0-9\s\-]+)</td>', tr)
                    score = score_m.group(1).replace(' ', '') if score_m else '--'
                    is_fin = ('完' in tr) or (score != '--' and score != '-' and score != '')
                    live_map[code] = {
                        'score': score if score != '-' else '--',
                        'is_finished': is_fin
                    }
    except Exception as e:
        print(f"[{datetime.now()}] Error fetching live scores: {e}")
    return live_map

def full_pipeline_sync(auto_push=True):
    if not os.path.exists(MATCHES_FILE):
        return

    with open(MATCHES_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    existing_matches = data.get('matches', [])
    existing_map = {m['code']: m for m in existing_matches}

    changes_made = False
    log_messages = []

    # 1. 扫描官方排期池：自动发现并上新未来场次（如星期一、星期二开售的比赛）
    official_pool = fetch_official_lottery_pool()
    newly_added = 0
    for of in official_pool:
        code = of['code']
        # 如果是新开售的场次，且本地没有
        if code not in existing_map:
            st, tip, cons, ratio, ana = generate_tactical_dossier(of['home'], of['away'], of['league'], of['odds'])
            new_item = {
                "code": code,
                "league": of['league'],
                "time": of['time'],
                "home": of['home'],
                "away": of['away'],
                "home_rank": "-",
                "away_rank": "-",
                "status": st,
                "form_home": ["W","D","W","L","D"],
                "form_away": ["D","W","L","W","W"],
                "odds": of['odds'],
                "consensus": cons,
                "consensus_ratio": ratio,
                "tip": tip,
                "score": "--",
                "result": "PENDING",
                "analysis": ana
            }
            existing_matches.append(new_item)
            existing_map[code] = new_item
            changes_made = True
            newly_added += 1
            log_messages.append(f"Auto-Added newly opened match: {code} {of['home']} vs {of['away']}")
        else:
            # 实时更新初赔（如果赔率变动）
            curr = existing_map[code]
            if of['odds'] != ["-", "-", "-"] and curr.get('odds') != of['odds']:
                curr['odds'] = of['odds']
                changes_made = True

    # 2. 扫描实时比分：自动完赛核销与移入大账本
    live_map = fetch_live_scores()
    newly_settled = 0
    for m in existing_matches:
        code = m['code']
        if m['result'] == 'PENDING':
            if code in live_map:
                info = live_map[code]
                if info['is_finished'] and info['score'] != '--':
                    score = info['score']
                    res = calculate_result(m['tip'], score)
                    m['score'] = score
                    m['status'] = '已完赛'
                    m['result'] = res
                    changes_made = True
                    newly_settled += 1
                    log_messages.append(f"Settled {code} ({m['home']} vs {m['away']}) -> 比分: {score}, 结果: {res}")

    if changes_made:
        data['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        data['total'] = len(existing_matches)
        data['matches'] = existing_matches

        with open(MATCHES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        with open(MATCHES_34_FALLBACK, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"[{datetime.now()}] Pipeline update: +{newly_added} new matches, settled {newly_settled} matches.")
        for msg in log_messages:
            print(f"  -> {msg}")

        if auto_push:
            os.chdir(WEB_DIR)
            subprocess.run(["git", "add", "data/official_matches.json", "data/matches_34.json", "index.html"], check=False)
            commit_title = f"Pipeline: +{newly_added} added, {newly_settled} settled ({datetime.now().strftime('%H:%M')})"
            subprocess.run(["git", "commit", "-m", commit_title], check=False)
            res = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
            print("Git push result:", res.stdout or res.stderr)
    else:
        print(f"[{datetime.now()}] Pipeline scan: Everything up-to-date. No new matches or finished scores.")

if __name__ == '__main__':
    full_pipeline_sync(auto_push=True)
