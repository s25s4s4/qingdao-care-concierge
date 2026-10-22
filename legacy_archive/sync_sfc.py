import re
import json
import os
import urllib.request
from datetime import datetime

SFC_FILE = "/var/www/football_live/data/sfc_matches.json"

def sync_sfc_live():
    if not os.path.exists(SFC_FILE): return
    try:
        url = "https://live.500.com/wanchang.php"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode('gbk', errors='ignore')
        
        with open(SFC_FILE, 'r', encoding='utf-8') as f:
            sfc_data = json.load(f)
            
        matches = sfc_data.get('matches', [])
        changed = False
        
        for m in matches:
            home = m.get('home', '')[:2]
            away = m.get('away', '')[:2]
            pos = html.find(home)
            while pos != -1:
                tr_start = html.rfind('<tr', 0, pos)
                tr_end = html.find('</tr>', pos)
                tr = html[tr_start:tr_end]
                if away in tr:
                    pk_m = re.findall(r'<a[^>]*class="clt[13]"[^>]*>([^<]*)</a>', tr)
                    if len(pk_m) >= 2 and pk_m[0].strip() != '':
                        fin_score = f"{pk_m[0].strip()}-{pk_m[1].strip()}"
                        status_m = re.search(r'status="([^"]+)"', tr)
                        status_code = status_m.group(1) if status_m else '4'
                        is_fin = (status_code == '4')
                        
                        if m.get('score') != fin_score or (is_fin and m.get('status') != '已完赛'):
                            m['score'] = fin_score
                            if is_fin:
                                m['status'] = '已完赛'
                                m['live_status'] = 'FIN'
                                p_sc = fin_score.split('-')
                                try:
                                    h_g, a_g = int(p_sc[0]), int(p_sc[1])
                                    outcome = '3' if h_g > a_g else ('1' if h_g == a_g else '0')
                                    m['outcome'] = outcome
                                    p = str(m.get('pick_primary') or '')
                                    s = str(m.get('pick_secondary') or '')
                                    u = str(m.get('pick_upset') or '')
                                    if outcome == p:
                                        m['result'] = 'HIT_PRIMARY'
                                        m['result_text'] = '首选命中'
                                    elif outcome == s:
                                        m['result'] = 'HIT_SECONDARY'
                                        m['result_text'] = '次选命中'
                                    elif outcome == u:
                                        m['result'] = 'HIT_UPSET'
                                        m['result_text'] = '防冷命中'
                                    else:
                                        m['result'] = 'MISS'
                                        m['result_text'] = '未中'
                                except Exception:
                                    pass
                            else:
                                m['status'] = '进行中'
                            changed = True
                    break
                pos = html.find(home, pos + 1)
                
        if changed:
            with open(SFC_FILE, 'w', encoding='utf-8') as f:
                json.dump(sfc_data, f, ensure_ascii=False, indent=2)
            with open('/var/www/football_live/sfc_matches.json', 'w', encoding='utf-8') as f:
                json.dump(sfc_data, f, ensure_ascii=False, indent=2)
            print(f"[{datetime.now()}] 传足14场比分与对错核销自动同步更新！")
    except Exception as e:
        print(f"[{datetime.now()}] SFC error: {e}")

if __name__ == '__main__':
    sync_sfc_live()
