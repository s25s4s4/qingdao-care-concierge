import urllib.request
import re
import json
import os
import subprocess
from datetime import datetime

MATCHES_FILE = r"E:\euro_intel_web\data\official_matches.json"
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
    
    # 严格判定
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

def fetch_live_scores():
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

def sync_and_audit(auto_push=True):
    if not os.path.exists(MATCHES_FILE):
        print(f"File not found: {MATCHES_FILE}")
        return
        
    with open(MATCHES_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    matches = data.get('matches', [])
    live_map = fetch_live_scores()
    
    updated = False
    new_settled = []
    
    for m in matches:
        code = m['code']
        # 针对尚未核销的比赛检查
        if m['result'] == 'PENDING':
            if code in live_map:
                info = live_map[code]
                if info['is_finished'] and info['score'] != '--':
                    score = info['score']
                    res = calculate_result(m['tip'], score)
                    m['score'] = score
                    m['status'] = '已完赛'
                    m['result'] = res
                    updated = True
                    new_settled.append(f"{code} {m['home']} vs {m['away']} -> 比分: {score}, 核销: {res}")
                    print(f"[{datetime.now()}] Match finished & audited: {code} -> {score} [{res}]")
                    
    if updated or not os.path.exists(r"E:\euro_intel_web\data\matches_34.json"):
        data['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(MATCHES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        with open(r"E:\euro_intel_web\data\matches_34.json", 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        print(f"[{datetime.now()}] Successfully saved updated match data.")
        
        if auto_push:
            os.chdir(WEB_DIR)
            subprocess.run(["git", "add", "data/official_matches.json", "data/matches_34.json", "index.html"], check=False)
            commit_msg = f"Auto-Audit: settled {len(new_settled)} matches ({', '.join(new_settled[:3])})"
            subprocess.run(["git", "commit", "-m", commit_msg], check=False)
            res = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
            print("Git push result:", res.stdout or res.stderr)
    else:
        print(f"[{datetime.now()}] Scan complete: No newly finished matches to settle.")

if __name__ == '__main__':
    sync_and_audit(auto_push=False)
