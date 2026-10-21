import os

html_path = r'E:\euro_intel_web\index.html'
with open(html_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 找到 renderSettledTable 中 2串1 计算的起始与结束
start_marker = "// 核心重构：实战 ROI 严格按 2串1 全息组合独立核算（符合柜台实票规则）！"
end_marker = "if (settledList.length === 0) {"

idx_start = content.find(start_marker)
idx_end = content.find(end_marker)

if idx_start == -1 or idx_end == -1:
    print("定位失败:", idx_start, idx_end)
    exit(1)

new_code = '''// 核心重构：实战 ROI 与策略对照严格按【真实单/双选复式注数】展开精算！
                        let totalParlayPairs = 0;       // 纯场次两两配对数
                        let totalMultiBets = 0;          // 双选防冷真实展开总注数
                        let hitMultiBets = 0;            // 双选防冷真实命中注数
                        let totalMultiReturn = 0.0;      // 双选防冷中奖金额(按SP复合相乘倍数)
                        
                        let totalSingleBets = 0;         // 纯首选单挑总注数 (等于对子数)
                        let hitSingleBets = 0;           // 纯首选单挑命中注数
                        let totalSingleReturn = 0.0;     // 纯首选单挑中奖金额(按SP复合相乘倍数)

                        if (todaySettledList.length >= 2) {
                            // 先预解析当天每场比赛的单双选选项及真实打出项
                            const parsedDayMatches = todaySettledList.map(m => {
                                const parsedOpts = parseMatchTipOptions(m);
                                const opts = parsedOpts.options; // 数组，如 ['胜', '平']
                                const isRq = !!m.is_only_rq;
                                
                                // 解析真实打出项
                                let actual = '';
                                let actualSp = 1.85;
                                const odds = m.odds || ['1.85', '3.20', '2.80'];
                                const sp_w = parseFloat(odds[0]) || 1.85;
                                const sp_d = parseFloat(odds[1]) || 3.20;
                                const sp_l = parseFloat(odds[2]) || 2.80;
                                
                                if (m.score && m.score.includes('-')) {
                                    const [h, a] = m.score.split('-').map(x => parseInt(x.trim()));
                                    if (isRq) {
                                        const rang = parseInt(m.rang || '-1');
                                        const diff = h + rang - a;
                                        if (diff > 0) { actual = '让胜'; actualSp = sp_w; }
                                        else if (diff === 0) { actual = '让平'; actualSp = sp_d; }
                                        else { actual = '让负'; actualSp = sp_l; }
                                    } else {
                                        if (h > a) { actual = '胜'; actualSp = sp_w; }
                                        else if (h === a) { actual = '平'; actualSp = sp_d; }
                                        else { actual = '负'; actualSp = sp_l; }
                                    }
                                }
                                
                                // 首选单挑选项
                                const primaryOpt = opts[0] || (isRq ? '让胜' : '胜');
                                
                                return {
                                    m: m,
                                    options: opts,
                                    count: opts.length,
                                    primary: primaryOpt,
                                    actual: actual,
                                    actualSp: actualSp,
                                    isHitMulti: opts.includes(actual),
                                    isHitSingle: (primaryOpt === actual)
                                };
                            });

                            totalSingleBets = (todaySettledList.length * (todaySettledList.length - 1)) / 2;
                            totalParlayPairs = totalSingleBets;

                            for (let i = 0; i < parsedDayMatches.length; i++) {
                                for (let j = i + 1; j < parsedDayMatches.length; j++) {
                                    const p1 = parsedDayMatches[i];
                                    const p2 = parsedDayMatches[j];
                                    
                                    // 1. 双选防冷：两场比赛选项交叉相乘 (单x单=1注, 单x双=2注, 双x双=4注)
                                    const pairMultiBets = p1.count * p2.count;
                                    totalMultiBets += pairMultiBets;
                                    
                                    if (p1.isHitMulti && p2.isHitMulti) {
                                        hitMultiBets += 1; // 一场比赛只有一个真实赛果，无论选了几项最多打出 1 注中奖
                                        totalMultiReturn += (p1.actualSp * p2.actualSp);
                                    }
                                    
                                    // 2. 纯首选单挑：永远只买 1 注
                                    if (p1.isHitSingle && p2.isHitSingle) {
                                        hitSingleBets += 1;
                                        totalSingleReturn += (p1.actualSp * p2.actualSp);
                                    }
                                }
                            }
                        }

                        // 综合实战 ROI：以真实包含双选防冷的总注数为投入基准 (每注 1000 元或 2 元同比例)
                        if (totalMultiBets > 0) {
                            const todayRoi = ((totalMultiReturn - totalMultiBets) / totalMultiBets) * 100;
                            const sign = todayRoi >= 0 ? '+' : '';
                            const roiStr = `${sign}${todayRoi.toFixed(1)}%`;
                            roiElem.innerText = roiStr;
                            roiElem.style.color = todayRoi >= 0 ? 'var(--accent-gold)' : '#f85149';

                            const tipRoiVal = document.getElementById('tip-roi-val');
                            const tipRoiCost = document.getElementById('tip-roi-cost');
                            const tipRoiStatus = document.getElementById('tip-roi-status');
                            const tipRoiProfit = document.getElementById('tip-roi-profit');
                            if (tipRoiVal) {
                                tipRoiVal.innerText = roiStr;
                                tipRoiVal.style.color = todayRoi >= 0 ? 'var(--accent-gold)' : '#f85149';
                            }
                            
                            // 假设每注 1000 元标准大额出票
                            const STAKE_PER_BET = 1000;
                            const totalStake = totalMultiBets * STAKE_PER_BET;
                            const totalWin = Math.round(totalMultiReturn * STAKE_PER_BET);
                            const netProfit = totalWin - totalStake;

                            if (tipRoiCost) tipRoiCost.innerText = totalStake.toLocaleString();
                            if (tipRoiStatus) tipRoiStatus.innerText = netProfit >= 0 ? '净赚' : '回撤';
                            if (tipRoiProfit) {
                                tipRoiProfit.innerText = Math.abs(netProfit).toLocaleString();
                                tipRoiProfit.style.color = netProfit >= 0 ? '#3fb950' : '#f85149';
                            }

                            // 动态渲染【前一完赛日 2串1 策略双轨对比卡片】
                            const compareContainer = document.getElementById('audit-compare-container');
                            const compareTitle = document.getElementById('audit-compare-day-title');
                            if (compareContainer && todaySettledList.length >= 2) {
                                if (compareTitle) compareTitle.innerText = `${activeDayKey}档期 (${todaySettledList.length}场比赛 · 基准1000元/注)`;

                                const singleCost = totalSingleBets * STAKE_PER_BET;
                                const singleWin = Math.round(totalSingleReturn * STAKE_PER_BET);
                                const singleProfit = singleWin - singleCost;
                                const singleRoi = ((totalSingleReturn - totalSingleBets) / totalSingleBets) * 100;
                                const singleColor = singleProfit >= 0 ? '#3fb950' : '#f85149';

                                const multiCost = totalStake;
                                const multiWin = totalWin;
                                const multiProfit = netProfit;
                                const multiRoi = todayRoi;
                                const multiColor = multiProfit >= 0 ? '#3fb950' : '#f85149';

                                compareContainer.innerHTML = `
                                    <div style="background: rgba(22, 27, 34, 0.8); border: 1px solid rgba(88, 166, 255, 0.3); border-radius: 6px; padding: 8px;">
                                        <div style="font-size: 11px; font-weight: 700; color: #58a6ff; margin-bottom: 4px;">🎯 只选【首选单挑】2串1</div>
                                        <div style="font-size: 10px; color: var(--text-secondary); line-height: 1.4;">
                                            • <b>实际注数</b>: 共 <b>${totalSingleBets}</b> 注 (每场纯单选)<br>
                                            • <b>命中情况</b>: 命中 <b style="color:#fff;">${hitSingleBets}</b> / ${totalSingleBets} 注<br>
                                            • <b>返还金额</b>: ${singleWin.toLocaleString()} 元<br>
                                            • <b>实际净盈亏</b>: <b style="color: ${singleColor};">${singleProfit >= 0 ? '+' : ''}${singleProfit.toLocaleString()} 元</b><br>
                                            • <b>真实 ROI</b>: <b style="color: ${singleColor};">${singleRoi >= 0 ? '+' : ''}${singleRoi.toFixed(1)}%</b>
                                        </div>
                                    </div>
                                    <div style="background: rgba(22, 27, 34, 0.8); border: 1px solid rgba(63, 185, 80, 0.3); border-radius: 6px; padding: 8px;">
                                        <div style="font-size: 11px; font-weight: 700; color: #3fb950; margin-bottom: 4px;">🛡️ 包含【双选防冷】2串1</div>
                                        <div style="font-size: 10px; color: var(--text-secondary); line-height: 1.4;">
                                            • <b>实际注数</b>: 共 <b style="color:#fbbf24;">${totalMultiBets}</b> 注 (展开复式组合)<br>
                                            • <b>命中情况</b>: 命中 <b style="color:#fff;">${hitMultiBets}</b> / ${totalMultiBets} 注<br>
                                            • <b>返还金额</b>: ${multiWin.toLocaleString()} 元<br>
                                            • <b>实际净盈亏</b>: <b style="color: ${multiColor};">${multiProfit >= 0 ? '+' : ''}${multiProfit.toLocaleString()} 元</b><br>
                                            • <b>真实 ROI</b>: <b style="color: ${multiColor};">${multiRoi >= 0 ? '+' : ''}${multiRoi.toFixed(1)}%</b>
                                        </div>
                                    </div>
                                `;
                            }
                        } else {
                            roiElem.innerText = '待完赛';
                            roiElem.style.color = 'var(--text-secondary)';
                        }
                    } else {
                        hitRateElem.innerText = '--';
                        statTotalElem.innerText = `0 / ${ALL_OFFICIAL_MATCHES.length}`;
                        roiElem.innerText = '待完赛';
                        roiElem.style.color = 'var(--text-secondary)';
                
                        const tipRoiVal = document.getElementById('tip-roi-val');
                        const tipRoiCost = document.getElementById('tip-roi-cost');
                        const tipRoiProfit = document.getElementById('tip-roi-profit');
                        if (tipRoiVal) tipRoiVal.innerText = '待完赛';
                        if (tipRoiCost) tipRoiCost.innerText = '0';
                        if (tipRoiProfit) tipRoiProfit.innerText = '0';
                    }

                    '''

new_content = content[:idx_start] + new_code + content[idx_end:]

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(new_content)

print("已成功重构 index.html 中双选防冷 2 串 1 的注数与 ROI 算法！")
