import sys, os, json
sys.path.insert(0, r'E:\euro_intel_web')
from deep_reasoning_engine import run_tri_model_deep_reasoning
from sync_live_matches import fetch_official_lottery_pool
import verify

MATCHES_FILE = r'E:\euro_intel_web\data\official_matches.json'
MATCHES_34_FALLBACK = r'E:\euro_intel_web\data\matches_34.json'

with open(MATCHES_FILE, 'r', encoding='utf-8') as f:
    data = json.load(f)

matches = data.get('matches', [])
pool = fetch_official_lottery_pool()
pool_map = {p['code']: p for p in pool}

print("=== 开始对周二全部 9 场比赛进行独立深度对抗推演与重新生成 ===")

tue_matches = [m for m in matches if m.get('code', '').startswith('周二')]
print(f"待处理周二比赛场次: {len(tue_matches)}")

for m in tue_matches:
    code = m['code']
    pool_item = pool_map.get(code)
    if not pool_item:
        print(f"警告: 官方池中未找到 {code}，跳过")
        continue

    # 1. 确保 odds, is_only_rq, rang 真实
    m['odds'] = pool_item['odds']
    m['odds_nspf'] = pool_item.get('odds_nspf', ['-', '-', '-'])
    m['odds_rq'] = pool_item.get('odds_rq', ['-', '-', '-'])
    m['is_only_rq'] = pool_item.get('is_only_rq', False)
    m['rang'] = pool_item.get('rang', '0')

    print(f"\n[正在推演 {code}]: {pool_item['home']} vs {pool_item['away']}")
    print(f"  真实赔率: {m['odds']} | 是否单开让球: {m['is_only_rq']} | 让球数: {m['rang']}")

    try:
        # 调用大模型生成案卷
        res = run_tri_model_deep_reasoning(pool_item)
        
        m['status'] = "三模型深度裁决"
        m['tip'] = res['tip']
        m['consensus_ratio'] = res['consensus_ratio']
        m['consensus'] = f"{res['tip']} ({res['consensus_ratio']}%)"
        m['consensus_breakdown'] = res.get('consensus_breakdown', {
            'odds_score': 75.0, 'intel_score': 75.0, 'tipster_score': 75.0, 'math_score': 75.0
        })
        m['predicted_scores'] = res.get('predicted_scores', ['1-1', '2-1', '1-2'])
        m['predicted_goals'] = res.get('predicted_goals', ['2', '3'])
        m['analysis'] = f"{pool_item['home']}对阵{pool_item['away']}，三模型对抗研判首选【{res['tip']}】。"
        m['dossier'] = {
            "summary": f"{pool_item['home']}对阵{pool_item['away']}，三模型对抗研判首选【{res['tip']}】。",
            "fundamental": res.get("fundamental", ""),
            "tactical_conflict": res.get("tactical_conflict", ""),
            "market_attitude": res.get("market_attitude", ""),
            "decision_guide": res.get("decision_guide", "")
        }

        # 重新生成防篡改快照
        if 'prediction_snapshot' in m:
            del m['prediction_snapshot']
        verify.freeze(m)

        print(f"  -> 成功得出研判: 【{m['tip']}】 ({m['consensus_ratio']}%)")
        print(f"  -> 黄金三角比分: {m['predicted_scores']}")
        print(f"  -> 案卷赔率描述: {m['dossier']['market_attitude'][:50]}...")
    except Exception as e:
        print(f"  -> {code} 推演报错: {e}")

# 保存写回两个 json 文件
with open(MATCHES_FILE, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

with open(MATCHES_34_FALLBACK, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("\n=== 全部周二比赛推演重构完毕，已成功写入 official_matches.json 和 matches_34.json ===")
