# 小杨说体彩 · 竞彩足球数据站

青岛本地彩票店的竞彩足球数据站。**www.qingdaocare.top**

前端是一个单文件 `index.html`（约 3500 行，无构建、无依赖），后端是一组 Python 脚本，
由 Windows 计划任务每分钟驱动一次，产出 JSON 推到 GitHub Pages + 阿里云双节点。

> 仓库名 `qingdao-care-concierge` 是历史遗留（这块地最早是另一个项目），与站点内容无关。
> 旧项目的图片已移到 `_archive_local/`，不进版本库。

---

## 一、它做什么

给彩民看**今晚有哪些比赛、每场怎么看、昨天说对了没有**。

核心不是"预测"，是**可核验**：

- 每场赛前生成研判，开赛前把预测**哈希冻结**存档；
- 赛后用**两个独立比分源**结算，冲突只报警不自动改分；
- 前端明确标注这条预测是「✅ 赛前冻结」「🗂 历史回填·可复核」还是「⚠️ 未验证·不计准确率」。

没有凭据的预测不会被算进命中率。这是整个站最硬的部分——它让"我赛前就是这么说的"变成可查的。

---

## 二、目录

```
index.html              单文件前端（7 个页签 + 详情弹窗）
CNAME                   www.qingdaocare.top

# —— 采集 ——
sporttery.py            官方竞彩网关（在售场次 + 全玩法 SP）
sync_live_matches.py    主流水线：排期上新 → 比分三态 → 结算 → 归档 → 发布
sync_sfc.py             胜负彩（传足 14 场）数据
fetch_understat.py      无头 Edge 渲染 Understat，取五大联赛当季 xG

# —— 计算 ——
quant_engine.py         泊松 + 凯利去水 + 多维因子
deep_reasoning_engine.py  LLM 三模型交叉推演（走本地 :3000 网关）
team_stats.py           本地 14 年库算近期战绩 / 交锋
enrich_team_stats.py    把上面两项合并进 official_matches.json

# —— 校验 ——
verify.py               赛前冻结 + FotMob 独立结算
crosscheck.py           双源比分交叉校验，只报冲突
backfill_from_git.py    从 git 历史回填赛前预测快照
calibrate.py            分置信度区间的真实命中率与校准偏差

# —— 记录 ——
result_archive.py       赛果归档（data/match_results.jsonl）
odds_track.py           赔率轨迹 + CLV

data/                   全部产物（见下）
images/logo.jpg         唯一在用的图片
```

---

## 三、数据流

```
                    ┌─ sporttery 官方网关 ─┐
每分钟 FootballLiveAuditor │  live.500.com 比分  ├→ sync_live_matches.py
                    └─ FotMob 独立结算  ─┘         │
                                                   ↓
                                    data/official_matches.json
                                                   │
                          ┌────────────────────────┼────────────────────┐
                          ↓                        ↓                    ↓
                    git push                 scp 阿里云            jsdelivr purge
                 (GitHub Pages)          (47.121.185.16)          (刷 CDN 缓存)
                          └────────────────────────┴────────────────────┘
                                                   ↓
                                    前端 fetch（三级回退）+ SSE
```

前端数据源优先级：`api.qingdaocare.top`（阿里云，1.3s）→ `./data/`（Pages）→
`raw.githubusercontent.com`，分别 2.5s / 4s / 8s 超时。

---

## 四、data/ 里都是什么

| 文件 | 内容 | 谁写 |
|---|---|---|
| `official_matches.json` | **主数据**：全部场次 + 研判 + 比分 + 案卷 | sync_live_matches.py |
| `sfc_matches.json` | 胜负彩 14 场 | sync_sfc.py |
| `live_intel.json` | Telegram 情报流（另一个仓库产出） | telegram_football_monitor |
| `match_results.jsonl` | 赛果归档，一行一场 | result_archive.py |
| `odds_history.jsonl` | 赔率变动轨迹 | odds_track.py |
| `understat_teams.json` | 五大联赛当季战绩 + xG | fetch_understat.py |
| `team_aliases.json` | 中文队名 → 英文（157 条） | 手工维护 |
| `calibration.json` | 校准结果 | calibrate.py |
| `archive_stats.json` | 归档覆盖度日报 | result_archive.py |

`matches_34.json` 是 `official_matches.json` 的副本（旧版兼容），内容一致。

---

## 五、跑起来

计划任务（每 1 分钟）：

```
FootballLiveAuditor
  C:\Users\Administrator\.hermes\hermes-agent\venv\Scripts\pythonw.exe E:\euro_intel_web\sync_live_matches.py
```

手动跑一次（会写文件、提交、推送）：

```
cd E:\euro_intel_web
python sync_live_matches.py
```

只想看会改什么、不落盘：

```
python -c "import sync_live_matches as S; S.full_pipeline_sync(auto_push=False)"
```

---

## 六、几个必须知道的坑

**1. 竞彩场次编号每周复用。**
`周一001` 在 14 年数据里出现过 518 次。任何按 `code` 去重的地方都要带上日期，
否则下周同编号的比赛会被当成"已处理"静默跳过。（`result_archive.py` 踩过，已改成 `(code, date)`）

**2. 前端有功能开关，下线的产品线代码还在。**
`FEATURE_PARLAY_ROI = false` —— 实战串关 / ROI 整线已下架。
原因：14 年 80,284 场回测，在 11.7% 抽水下 2串1 不存在正期望（最优组合 −17.0%）。
代码留着是为了随时能重开，但导航里点不到。

**3. Understat 抓取会静默抓空。**
无头 Edge 偶发 5 个联赛全失败，写进一个 `leagues: {}` 的空文件。
`stale()` 现在把"空结果"也当作过期，会立刻重抓——否则要白等 6 小时，
期间所有场次的当季 xG 都是空的。

**4. 详情弹窗里的"泊松"不是独立模型。**
它是用**去水后的胜平负概率反推 xG**，再展开成比分/进球分布。
本质是赔率的另一种写法，不产生独立于市场的预测。所以标签写的是"由官方 SP 反推"，
不是"精算"。`xG 回归信号`同理，只提示，不改推荐。

**5. 每分钟提交一次，`.git` 会长得很快。**
每次提交都带 700KB 的 `official_matches.json`，一天 1000+ 次提交。
目前 `.git` 已 76MB。如果嫌大，把数据文件改成每天提交一次、代码随时提交。

---

## 七、本地备份

- `_archive_local/`：调试截图、旧图片、`.bak` 快照（9MB，不进版本库，可随时删）
- Telegram 情报引擎在另一个仓库：`E:\telegram_football_monitor`
