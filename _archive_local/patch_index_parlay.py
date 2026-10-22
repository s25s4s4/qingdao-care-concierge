import os

html_path = r'E:\euro_intel_web\index.html'
with open(html_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 找到 renderParlayMatrix 的起始和结束位置
start_str = '        // 渲染【实战串关 (2串1全息拓扑矩阵 + 单关直打)】\n        function renderParlayMatrix() {'
end_str = '        // 渲染共识榜单 (按共识百分比排序)\n        function renderConsensusList() {'

idx_start = content.find(start_str)
idx_end = content.find(end_str)

if idx_start == -1 or idx_end == -1:
    print('定位失败:', idx_start, idx_end)
    exit(1)

new_code = '''        // 解析比赛赛前研判为体彩真实投注项 (支持单选与双选防冷)
        function parseMatchTipOptions(m) {
            const tip = m.tip || '';
            const isRq = !!m.is_only_rq;
            const prefix = isRq ? '让' : '';
            const opts = [];

            if (tip.includes('死胆') || tip.includes('主胜让胜')) {
                opts.push(prefix + '胜');
            } else if (tip === '主胜') {
                opts.push(prefix + '胜');
            } else if (tip === '客胜') {
                opts.push(prefix + '负');
            } else if (tip === '平局') {
                opts.push(prefix + '平');
            } else if (tip.includes('让负')) {
                opts.push('让负', '让平');
            } else if (tip.includes('让胜')) {
                opts.push('让胜');
            } else if (tip.includes('主不败') || tip.includes('主胜/防平') || tip.includes('平局/主胜')) {
                opts.push(prefix + '胜', prefix + '平');
            } else if (tip.includes('客不败') || tip.includes('客胜/防平') || tip.includes('平局/客胜') || tip.includes('双选平负') || tip.includes('客不败/首选客胜') || tip.includes('客不败/首选平') || tip.includes('客胜/进球数大')) {
                opts.push(prefix + '负', prefix + '平');
            } else if (tip.includes('双方进球') || tip.includes('进球数')) {
                if (tip.includes('客') || tip.includes('负')) opts.push(prefix + '负', prefix + '平');
                else opts.push(prefix + '胜', prefix + '平');
            } else {
                if (tip.includes('客')) opts.push(prefix + '负');
                else opts.push(prefix + '胜');
            }

            return {
                code: m.code,
                home: m.home,
                away: m.away,
                league: m.league,
                time: m.time,
                tip: tip,
                is_rq: isRq,
                options: opts,
                count: opts.length
            };
        }

        // 贪心启发式算法：求任意场次的最优 8 场 2 关打票覆盖方案 (100% 覆盖两两配对)
        function generateCoveringTickets(parsedMatches) {
            const n = parsedMatches.length;
            if (n < 2) return [];
            if (n <= 8) {
                return [Array.from({length: n}, (_, i) => i)];
            }

            const pairs = new Set();
            for (let i = 0; i < n; i++) {
                for (let j = i + 1; j < n; j++) {
                    pairs.add(`${i}_${j}`);
                }
            }

            const uncovered = new Set(pairs);
            const tickets = [];

            while (uncovered.size > 0) {
                const freq = new Array(n).fill(0);
                uncovered.forEach(pairKey => {
                    const [u, v] = pairKey.split('_').map(Number);
                    freq[u]++;
                    freq[v]++;
                });

                const sortedIndices = Array.from({length: n}, (_, i) => i).sort((a, b) => freq[b] - freq[a]);
                let bestBlock = sortedIndices.slice(0, 8);
                
                const calcGain = (block) => {
                    let g = 0;
                    for (let i = 0; i < block.length; i++) {
                        for (let j = i + 1; j < block.length; j++) {
                            const minIdx = Math.min(block[i], block[j]);
                            const maxIdx = Math.max(block[i], block[j]);
                            if (uncovered.has(`${minIdx}_${maxIdx}`)) g++;
                        }
                    }
                    return g;
                };

                let bestGain = calcGain(bestBlock);

                // 启发式随机搜索
                const poolSize = Math.min(n, 20);
                const pool = sortedIndices.slice(0, poolSize);
                for (let step = 0; step < 180; step++) {
                    const cand = [];
                    const poolCopy = [...pool];
                    while (cand.length < 8 && poolCopy.length > 0) {
                        const rIdx = Math.floor(Math.random() * poolCopy.length);
                        cand.push(poolCopy.splice(rIdx, 1)[0]);
                    }
                    const gain = calcGain(cand);
                    if (gain > bestGain) {
                        bestBlock = cand;
                        bestGain = gain;
                    }
                }

                for (let i = 0; i < bestBlock.length; i++) {
                    for (let j = i + 1; j < bestBlock.length; j++) {
                        const minIdx = Math.min(bestBlock[i], bestBlock[j]);
                        const maxIdx = Math.max(bestBlock[i], bestBlock[j]);
                        uncovered.delete(`${minIdx}_${maxIdx}`);
                    }
                }

                tickets.push(bestBlock.sort((a, b) => a - b));
            }

            return tickets;
        }

        // 渲染【实战串关 (体彩柜台极简打票专区)】
        function renderParlayMatrix() {
            const singlesContainer = document.getElementById('parlay-singles-list');
            const pairsContainer = document.getElementById('parlay-pairs-list');
            const totalTicketsElem = document.getElementById('parlay-total-tickets');
            const totalCostElem = document.getElementById('parlay-total-cost');
            const hitRateElem = document.getElementById('parlay-hit-rate');
            const roiElem = document.getElementById('parlay-roi-num');
            const batchTitleElem = document.getElementById('parlay-batch-title');

            if (!singlesContainer || !pairsContainer) return;

            singlesContainer.innerHTML = '';
            pairsContainer.innerHTML = '';

            // 1. 寻找当前在售待开赛与已完赛批次
            const pendingMatches = ALL_OFFICIAL_MATCHES.filter(m => m.result === 'PENDING');
            const settledMatches = ALL_OFFICIAL_MATCHES.filter(m => m.result !== 'PENDING');

            // 动态判定已完赛日期
            const distinctSettledDays = [];
            settledMatches.forEach(m => {
                const dk = m.code ? m.code.substring(0, 2) : '';
                if (dk && !distinctSettledDays.includes(dk)) distinctSettledDays.push(dk);
            });
            const weekWeight = {'周五': 1, '周六': 2, '周日': 3, '周一': 4, '周二': 5, '周三': 6, '周四': 7};
            distinctSettledDays.sort((a, b) => (weekWeight[b] || 0) - (weekWeight[a] || 0));
            const latestSettledDay = distinctSettledDays[0] || '昨日';

            if (hitRateElem && hitRateElem.nextElementSibling) hitRateElem.nextElementSibling.innerText = `${latestSettledDay}串关命中率`;
            if (roiElem && roiElem.nextElementSibling) roiElem.nextElementSibling.innerText = `${latestSettledDay}实战ROI`;

            // 统计已完赛指标
            const latestDayMatches = settledMatches.filter(m => m.code && m.code.startsWith(latestSettledDay));
            if (latestDayMatches.length >= 2) {
                let hitPairs = 0;
                let totalPairs = 0;
                let totalReturn = 0.0;
                for (let i = 0; i < latestDayMatches.length; i++) {
                    for (let j = i + 1; j < latestDayMatches.length; j++) {
                        totalPairs++;
                        const m1 = latestDayMatches[i];
                        const m2 = latestDayMatches[j];
                        if (m1.result === 'HIT' && m2.result === 'HIT') {
                            hitPairs++;
                            totalReturn += 1.85 * 1.85;
                        }
                    }
                }
                if (totalPairs > 0) {
                    if (hitRateElem) hitRateElem.innerText = ((hitPairs / totalPairs) * 100).toFixed(1) + '%';
                    const roiVal = (((totalReturn - totalPairs) / totalPairs) * 100).toFixed(1);
                    if (roiElem) roiElem.innerText = `+${roiVal}%`;
                }
            }

            // 2. 单关直打专区
            const singleMatches = pendingMatches.filter(m => m.is_single);
            if (singleMatches.length > 0) {
                singleMatches.forEach(m => {
                    const card = document.createElement('div');
                    card.className = 'match-card';
                    card.style.borderLeft = '3px solid #f85149';
                    card.onclick = () => openDetail(m.code);
                    card.innerHTML = `
                        <div class="card-header">
                            <div>
                                <span class="league-tag" style="background: rgba(248, 81, 73, 0.2); color: #f85149; font-weight: 800;">🔥 官方单关 · ${m.code}</span>
                                <span style="font-size: 11px; color: var(--text-secondary); margin-left: 6px;">${m.league} · ${m.time}</span>
                            </div>
                            <span class="badge" style="background: rgba(248, 81, 73, 0.2); color: #f85149; font-weight: 700;">官方胜平负单关</span>
                        </div>
                        <div class="teams-box" style="margin: 8px 0;">
                            <div class="team-side home"><span class="team-name" style="font-weight: 700;">${m.home}</span></div>
                            <div class="vs-badge" style="font-size: 11px; color: var(--accent-gold);">VS</div>
                            <div class="team-side away"><span class="team-name" style="font-weight: 700;">${m.away}</span></div>
                        </div>
                        <div style="background: rgba(13, 17, 23, 0.6); padding: 8px 10px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center;">
                            <div><span style="font-size: 11px; color: var(--text-secondary);">推荐出票：</span><b style="color: var(--accent-gold); font-size: 13px;">${m.tip}</b></div>
                            <div style="font-size: 11px; color: var(--text-secondary);">进球数：<span style="color: #3fb950; font-weight: 700;">${(m.predicted_goals || []).join('、')}球</span></div>
                        </div>
                    `;
                    singlesContainer.appendChild(card);
                });
            } else {
                singlesContainer.innerHTML = `<div style="text-align: center; padding: 14px; font-size: 11px; color: var(--text-secondary); background: rgba(22, 27, 34, 0.5); border-radius: 6px;">今日官方暂未单开单独胜平负，所有比赛均在下方【打票专用清单】两两互串出票。</div>`;
            }

            // 3. 构建全息柜台打票专用卡片
            const distinctPendingDays = [];
            pendingMatches.forEach(m => {
                const dk = m.code ? m.code.substring(0, 2) : '';
                if (dk && !distinctPendingDays.includes(dk)) distinctPendingDays.push(dk);
            });
            distinctPendingDays.sort((a, b) => (weekWeight[a] || 0) - (weekWeight[b] || 0));
            const currentTargetDay = distinctPendingDays[0] || '今日';

            let activeDayMatches = pendingMatches.filter(m => m.code && m.code.startsWith(currentTargetDay));
            if (activeDayMatches.length < 2) activeDayMatches = pendingMatches;

            if (batchTitleElem) batchTitleElem.innerText = `${currentTargetDay}在售档期 (共${activeDayMatches.length}场比赛)`;

            const parsedMatches = activeDayMatches.map(parseMatchTipOptions);
            const ticketIndices = generateCoveringTickets(parsedMatches);

            let allTicketsCost = 0;

            ticketIndices.forEach((tIndices, tIdx) => {
                let ticketBets = 0;
                const matchItemsHtml = [];

                for (let i = 0; i < tIndices.length; i++) {
                    const m1 = parsedMatches[tIndices[i]];
                    const optBadges = m1.options.map(o => {
                        let bg = '#dc2626';
                        if (o.includes('平')) bg = '#2563eb';
                        else if (o.includes('负')) bg = '#16a34a';
                        return `<span style="background:${bg}; color:#fff; border-radius:3px; padding:1px 5px; font-size:11px; font-weight:800;">${o}</span>`;
                    }).join(' ');

                    matchItemsHtml.push(`
                        <div style="display: flex; align-items: center; justify-content: space-between; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 6px; padding: 6px 10px;">
                            <div style="font-size: 12px; display: flex; align-items: center; gap: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                                <b style="color: var(--accent-gold); font-family: var(--font-mono); font-size: 11px;">${m1.code}</b>
                                <span style="font-weight: 600; color: #e2e8f0; font-size: 12px;">${m1.home}<span style="color:#64748b; font-size:10px; margin:0 3px;">vs</span>${m1.away}</span>
                            </div>
                            <div style="display: flex; gap: 4px; flex-shrink: 0;">${optBadges}</div>
                        </div>
                    `);

                    for (let j = i + 1; j < tIndices.length; j++) {
                        const m2 = parsedMatches[tIndices[j]];
                        ticketBets += m1.count * m2.count;
                    }
                }

                const ticketMoney = ticketBets * 2;
                allTicketsCost += ticketMoney;

                const card = document.createElement('div');
                card.className = 'parlay-combo-card';
                card.style.margin = '0 0 16px 0';
                card.style.background = 'linear-gradient(180deg, #161b22 0%, #0d1117 100%)';
                card.style.border = '2px solid rgba(56, 189, 248, 0.4)';
                card.style.borderRadius = '12px';
                card.style.padding = '12px 14px';
                card.style.boxShadow = '0 6px 18px rgba(0, 0, 0, 0.45)';

                card.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255, 255, 255, 0.1); padding-bottom: 8px; margin-bottom: 10px;">
                        <div style="display: flex; align-items: center; gap: 6px;">
                            <span style="background: #2563eb; color: #fff; border-radius: 4px; padding: 2px 7px; font-weight: 800; font-size: 12px; font-family: var(--font-mono);">
                                第 ${String(tIdx + 1).padStart(2, '0')} 张票
                            </span>
                            <span style="font-size: 11.5px; color: var(--accent-gold); font-weight: 700;">
                                【过关：2关】(8场两两组合)
                            </span>
                        </div>
                        <div style="text-align: right;">
                            <span style="font-size: 11px; color: #8b949e;">共 <b>${ticketBets}</b> 注</span> · 
                            <span style="font-size: 15px; font-weight: 900; color: #fbbf24; font-family: var(--font-mono);">${ticketMoney} 元</span>
                        </div>
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr; gap: 6px;">
                        ${matchItemsHtml.join('')}
                    </div>
                `;
                pairsContainer.appendChild(card);
            });

            if (totalTicketsElem) totalTicketsElem.innerText = ticketIndices.length + ' 张';
            if (totalCostElem) totalCostElem.innerText = allTicketsCost.toLocaleString() + ' 元';
        }\n\n'''

new_content = content[:idx_start] + new_code + content[idx_end:]

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(new_content)

print('已成功无缝替换 index.html 中的串关渲染逻辑！')
