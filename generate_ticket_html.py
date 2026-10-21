import json, random

with open(r'E:\euro_intel_web\data\official_matches.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

sat_matches = [m for m in d['matches'] if '周六' in m['code']]

def parse_opts(tip, is_only_rq=False):
    prefix = '让' if is_only_rq else ''
    if any(k in tip for k in ['死胆', '主胜让胜']) or tip in ['主胜', '客胜', '平局']:
        return [prefix + ('负' if '客' in tip else ('平' if '平' in tip else '胜'))]
    if '主不败' in tip or '主胜/防平' in tip or '平局/主胜' in tip:
        return [prefix + '胜', prefix + '平']
    if '客不败' in tip or '客胜/防平' in tip or '平局/客胜' in tip or '双选平负' in tip or '客不败/首选客胜' in tip or '客不败/首选平' in tip or '客胜/进球数大' in tip:
        return [prefix + '负', prefix + '平']
    if '让负' in tip:
        return ['让负', '让平']
    if '平局/客胜' in tip:
        return [prefix + '负']
    return [prefix + '胜']

match_dict = {}
for i, m in enumerate(sat_matches):
    idx = i + 1
    opts = parse_opts(m.get('tip', ''), m.get('is_only_rq', False))
    match_dict[idx] = {
        'code': m['code'],
        'home': m['home'],
        'away': m['away'],
        'league': m['league'],
        'time': m['time'],
        'tip': m['tip'],
        'opts': opts,
        'len': len(opts)
    }

random.seed(42)
pairs = set((i, j) for i in range(1, 31) for j in range(i+1, 31))
uncovered = set(pairs)
tickets = []

while uncovered:
    freq = {i: 0 for i in range(1, 31)}
    for u, v in uncovered:
        freq[u] += 1
        freq[v] += 1
    candidates = sorted(range(1, 31), key=lambda x: freq[x], reverse=True)
    best_b = candidates[:8]
    best_g = len(set((min(best_b[i], best_b[j]), max(best_b[i], best_b[j])) for i in range(8) for j in range(i+1, 8)) & uncovered)
    for _ in range(300):
        cand = random.sample(candidates[:18], 8)
        b_pairs = set((min(cand[i], cand[j]), max(cand[i], cand[j])) for i in range(8) for j in range(i+1, 8))
        g = len(b_pairs & uncovered)
        if g > best_g:
            best_b = cand
            best_g = g
    b_pairs = set((min(best_b[i], best_b[j]), max(best_b[i], best_b[j])) for i in range(8) for j in range(i+1, 8))
    uncovered -= b_pairs
    tickets.append(sorted(best_b))

# 生成 HTML 内容
html_cards = []
total_money = 0
for idx, t in enumerate(tickets):
    bets = 0
    match_rows = []
    for i in range(8):
        m1 = match_dict[t[i]]
        # 样式定义
        opt_tags = []
        for o in m1['opts']:
            if '胜' in o:
                opt_tags.append(f'<span class="tag tag-win">{o}</span>')
            elif '平' in o:
                opt_tags.append(f'<span class="tag tag-draw">{o}</span>')
            else:
                opt_tags.append(f'<span class="tag tag-loss">{o}</span>')
        opt_html = ''.join(opt_tags)
        match_rows.append(f'''
        <div class="m-item">
            <div class="m-code">{m1['code']}</div>
            <div class="m-teams">{m1['home']}<span class="vs">vs</span>{m1['away']}</div>
            <div class="m-opts">{opt_html}</div>
        </div>
        ''')
        for j in range(i + 1, 8):
            m2 = match_dict[t[j]]
            bets += m1['len'] * m2['len']
    money = bets * 2
    total_money += money
    
    html_cards.append(f'''
    <div class="ticket-card">
        <div class="ticket-header">
            <div class="ticket-num">第 {idx+1:02d} 张票</div>
            <div class="ticket-method">【过关：2关】(8场两两组合)</div>
            <div class="ticket-meta"><b>{bets}</b> 注 · <span class="price">{money} 元</span></div>
        </div>
        <div class="m-grid">
            {''.join(match_rows)}
        </div>
    </div>
    ''')

full_html = f'''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>体彩实体店柜台打票专用表</title>
<style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
        background: #0b0f19;
        color: #f1f5f9;
        padding: 24px;
        width: 1200px;
        margin: 0 auto;
    }}
    .header-banner {{
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border: 2px solid #334155;
        border-radius: 14px;
        padding: 20px 24px;
        margin-bottom: 20px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }}
    .title-box h1 {{
        font-size: 24px;
        color: #f8fafc;
        display: flex;
        align-items: center;
        gap: 10px;
    }}
    .badge {{
        background: #d97706;
        color: #fff;
        font-size: 13px;
        padding: 3px 8px;
        border-radius: 6px;
        font-weight: 800;
    }}
    .rule-desc {{
        font-size: 13px;
        color: #94a3b8;
        margin-top: 6px;
        line-height: 1.5;
    }}
    .stats-summary {{
        display: flex;
        gap: 16px;
        background: rgba(15, 23, 42, 0.8);
        border: 1px solid #475569;
        border-radius: 10px;
        padding: 12px 20px;
        text-align: right;
    }}
    .stat-item .val {{
        font-size: 22px;
        font-weight: 800;
        color: #38bdf8;
    }}
    .stat-item .val.gold {{ color: #fbbf24; }}
    .stat-item .lbl {{ font-size: 11px; color: #64748b; margin-top: 2px; }}

    .grid-container {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 14px;
    }}
    .ticket-card {{
        background: #131b2e;
        border: 1px solid #1e293b;
        border-radius: 10px;
        padding: 12px 14px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3);
    }}
    .ticket-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid #1e293b;
        padding-bottom: 8px;
        margin-bottom: 10px;
    }}
    .ticket-num {{
        background: #2563eb;
        color: #fff;
        font-weight: 800;
        font-size: 13px;
        padding: 2px 8px;
        border-radius: 4px;
    }}
    .ticket-method {{
        font-size: 12px;
        color: #94a3b8;
        font-weight: 600;
    }}
    .ticket-meta {{
        font-size: 13px;
        color: #cbd5e1;
    }}
    .ticket-meta .price {{
        color: #fbbf24;
        font-weight: 800;
    }}
    .m-grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 6px 12px;
    }}
    .m-item {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: rgba(15, 23, 42, 0.5);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 6px;
        padding: 5px 8px;
        font-size: 12px;
    }}
    .m-code {{
        color: #fbbf24;
        font-weight: 800;
        font-size: 11px;
    }}
    .m-teams {{
        color: #e2e8f0;
        font-weight: 600;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 140px;
    }}
    .vs {{ color: #64748b; font-size: 10px; margin: 0 3px; font-weight: normal; }}
    .m-opts {{ display: flex; gap: 3px; }}
    .tag {{
        padding: 1px 5px;
        border-radius: 3px;
        font-size: 11px;
        font-weight: 800;
        line-height: 1.2;
    }}
    .tag-win {{ background: #dc2626; color: #fff; }}
    .tag-draw {{ background: #2563eb; color: #fff; }}
    .tag-loss {{ background: #16a34a; color: #fff; }}
</style>
</head>
<body>

<div class="header-banner">
    <div class="title-box">
        <h1>体彩终端机 · 全息 2串1 极简出票指引表 <span class="badge">店主柜台核照专用</span></h1>
        <div class="rule-desc">
            • <b>出票操作铁律</b>：每张票严格在体彩机勾选指定的 <b>8 场比赛</b>，过关方式直接勾选 <b>【2关】</b>。<br>
            • <b>单双选深度防冷</b>：单选死胆选1项，胶着战双选防平选2项。机器自动两两组合，<b>27 张票 100% 锁死全部 435 对 2串1</b>！
        </div>
    </div>
    <div class="stats-summary">
        <div class="stat-item">
            <div class="val">30 场</div>
            <div class="lbl">全天在售</div>
        </div>
        <div class="stat-item">
            <div class="val">435 对</div>
            <div class="lbl">全息2串1组合</div>
        </div>
        <div class="stat-item">
            <div class="val gold">27 张</div>
            <div class="lbl">出票总张数</div>
        </div>
        <div class="stat-item">
            <div class="val gold">{total_money:,} 元</div>
            <div class="lbl">实投总金额</div>
        </div>
    </div>
</div>

<div class="grid-container">
    {''.join(html_cards)}
</div>

</body>
</html>
'''

with open(r'E:\euro_intel_web\ticket_table.html', 'w', encoding='utf-8') as f:
    f.write(full_html)

print('已成功生成 HTML 文件: E:/euro_intel_web/ticket_table.html')
