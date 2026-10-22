import json
import os
import subprocess

MATCHES_FILE = r"E:\euro_intel_web\data\matches_34.json"

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
    
    # 判定逻辑
    if "主胜" in tip:
        if h > a: return "HIT"
    if "客胜" in tip:
        if a > h: return "HIT"
    if "平" in tip and "客不败" not in tip and "主不败" not in tip:
        if h == a: return "HIT"
    if "主不败" in tip:
        if h >= a: return "HIT"
    if "客不败" in tip:
        if a >= h: return "HIT"
    if "进球数3+" in tip or "大球" in tip:
        if total >= 3: return "HIT"
    if "双方进球" in tip:
        if h > 0 and a > 0: return "HIT"
    if "让负/防让平" in tip:
        if a >= h or h - a == 1: return "HIT"
    if "让胜/防让平" in tip:
        if h >= a or a - h == 1: return "HIT"
    if "让胜" in tip:
        if h - a >= 2: return "HIT"
    if "让负" in tip:
        if a - h >= 1 or a == h: return "HIT"

    # 如果明确建议但未满足
    if any(k in tip for k in ["主胜", "客胜", "平局", "进球数", "让胜", "让负"]):
        return "MISS"
        
    return "PENDING"

def update_scores(score_dict, auto_push=True):
    with open(MATCHES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    matches = data["matches"]
    updated_count = 0
    for m in matches:
        code = m["code"]
        if code in score_dict:
            score = score_dict[code]
            m["score"] = score
            m["status"] = "已完赛"
            m["result"] = calculate_result(m["tip"], score)
            updated_count += 1
            print(f"Updated {code} ({m['home']} vs {m['away']}) -> 比分: {score}, 核销: {m['result']}")
            
    with open(MATCHES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"\nSuccessfully updated {updated_count} matches in matches_34.json.")
    
    if auto_push:
        os.chdir(r"E:\euro_intel_web")
        subprocess.run(["git", "add", "data/matches_34.json", "index.html"], check=True)
        subprocess.run(["git", "commit", "-m", f"Audit: updated {updated_count} match scores and verification results"], check=False)
        res = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
        print("Git push result:", res.stdout or res.stderr)

if __name__ == "__main__":
    # 示例更新已完场的比赛
    test_scores = {
        "周六001": "2-0", # 麦克阿瑟主胜 -> 命中
        "周六002": "3-1", # 鹿岛鹿角主胜 -> 命中
        "周六003": "2-0", # 蔚山现代让胜 -> 命中
        "周六005": "0-1", # 柏太阳神vs名古屋鲸 -> 建议 平局/客胜 -> 命中
        "周六006": "1-1", # 宫崎牛鸟vs磐田喜悦 -> 建议 客胜 -> 失误 (客冷打平)
        "周六014": "2-1", # 不来梅主胜 -> 命中
    }
    update_scores(test_scores, auto_push=False)
