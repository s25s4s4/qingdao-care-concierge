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
sync_live_matches.py    主流水线：排期上新 → 比分三态 → 结算 → 归档 → 清理 → 发布
sync_sfc.py             胜负彩（传足 14 场）数据
fetch_understat.py      无头 Edge 渲染 Understat，取五大联赛当季 xG

# —— 计算 ——
quant_engine.py         泊松 + 凯利去水 + 多维因子
deep_reasoning_engine.py  LLM 三模型交叉推演（走本地 :3000 网关，默认关闭）
team_stats.py           本地 14 年库算近期战绩 / 交锋（mtime 缓存）
enrich_team_stats.py    把上面两项合并进 official_matches.json

# —— 校验 ——
verify.py               赛前冻结 + FotMob 独立结算
crosscheck.py           双源比分交叉校验，只报冲突
backfill_from_git.py    从 git 历史回填赛前预测快照
calibrate.py            分置信度区间的真实命中率与校准偏差
reconcile_snapshots.py  一次性订正：展示/结算口径对齐赛前冻结快照（2026-10-22）

# —— 记录 ——
result_archive.py       赛果归档（data/match_results.jsonl）
odds_track.py           赔率轨迹 + CLV

data/                   全部产物（见下）
images/logo.jpg         唯一在用的图片
sync_live.log           主流水线日志（pythonw 无控制台，排查看它）
```

> `matches_34.json` 已于 2026-10-22 停写停推（前端与服务器均不读取）。
> `temp_sync.py` / `refetch_tuesday.py` / `settle_matches.py` / `patch_*.py`
> 是历史一次性脚本，已移入 `_archive_local/`，随时可删。

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

前端数据源优先级：`api.qingdaocare.top`（阿里云，1.3s）→ `raw.githubusercontent.com`（2.5s）
→ `./data/`（Pages 本地副本，4s），分别超时后自动降级。

---

## 四、data/ 里都是什么

| 文件 | 内容 | 谁写 |
|---|---|---|
| `official_matches.json` | **主数据**：全部场次 + 研判 + 比分 + 案卷 | sync_live_matches.py |
| `sfc_matches.json` | 胜负彩 14 场 | sync_sfc_fixtures.py |
| `live_intel.json` | Telegram 情报流（另一个仓库产出） | telegram_football_monitor |
| `match_results.jsonl` | 赛果归档，一行一场 | result_archive.py |
| `odds_history.jsonl` | 赔率变动轨迹 | odds_track.py |
| `understat_teams.json` | 五大联赛当季战绩 + xG | fetch_understat.py |
| `team_aliases.json` | 中文队名 → 英文（157 条） | 手工维护 |
| `calibration.json` | 校准结果 | calibrate.py |
| `archive_stats.json` | 归档覆盖度日报 | result_archive.py |

本地缓存（gitignored，自动重建）：`team_stats_index.pkl`（14 年库索引）、
`history_indexed_cache.json`（同赔样本）、`team_live_form_cache.json`（球队近况 6h）。
`matches_34.json` 已于 2026-10-22 停写停推（前端与服务器均不读取）。

---

## 五、跑起来

计划任务：

| 任务名 | 频率 | 跑什么 |
|---|---|---|
| `FootballLiveAuditor` | 每 1 分钟 | `sync_live_matches.py`（主流水线） |
| `SfcFixtureSync` | 每 10 分钟 | `sync_sfc_fixtures.py`（传足换期，出赔率后补选号） |
| `TelegramFootballMonitor` | 每 5 分钟 | 另一个仓库的 `monitor_engine.py` |

> **`FootballLiveAuditor` 必须保持启用。** 停售锁定、赛前冻结、赛后结算、
> 新场次进场只由它完成——阿里云上的 cloud worker 只更新比分，不算命中不锁场。
> 2026-10-22 曾因任务被禁用导致站点停摆 4 小时，改任何代码后记得确认它是「就绪」。

```
FootballLiveAuditor
  C:\Users\Administrator\.hermes\hermes-agent\venv\Scripts\pythonw.exe E:\euro_intel_web\sync_live_matches.py

SfcFixtureSync
  C:\Users\Administrator\.hermes\hermes-agent\venv\Scripts\pythonw.exe E:\euro_intel_web\sync_sfc_fixtures.py
```

传足的日志在 `sfc_sync.log`（pythonw 没有控制台，所以落文件）。

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
`周一001` 在 14 年数据里出现过 518 次。判重必须带开赛日期：
`sync_live_matches.match_identity(code, date)` 用 `(编号, 完整日期)` 做键，
`result_archive` 按 `(code, date)` 去重，`rule_engine.settle_identity` 按快照取结算口径。
（2026-10-22 之前添加入口只按编号判重，实测把整周在售比赛全挡住过。）

**2. 前端有功能开关，下线的产品线代码还在。**
`FEATURE_PARLAY_ROI = false` —— 实战串关 / ROI 整线已下架。
原因：14 年 80,284 场回测，在 11.7% 抽水下 2串1 不存在正期望（最优组合 −17.0%）。
代码留着是为了随时能重开，但导航里点不到。

**3. 冻结即承诺，口径以快照为准。**
停售前 tip 不再被最新赔率重算（`normalize_match` 把有快照的场次按 history 处理）；
`verify.settle` / `validate_matches` / `settle_identity` 全部优先取快照的
tip / rang / is_only_rq。开赛中冻结的快照（frozen_mid_match）不是赛前承诺，
按当前 tip 结算，且不进校准主口径。

**4. 旧赛果 14 天清理。**
归档先写 `match_results.jsonl`（14 年库的来源），再按保留天数裁剪
`official_matches.json`，只清理 HIT/MISS 的旧场次。审计账本保留最近两周。

**5. Understat 抓取会静默抓空。**
无头 Edge 偶发 5 个联赛全失败，写进一个 `leagues: {}` 的空文件。
`stale()` 现在把"空结果"也当作过期，会立刻重抓——否则要白等 6 小时，
期间所有场次的当季 xG 都是空的。

**6. 详情弹窗里的"泊松"不是独立模型。**
它是用**去水后的胜平负概率反推 xG**，再展开成比分/进球分布。
本质是赔率的另一种写法，不产生独立于市场的预测。所以标签写的是"由官方 SP 反推"，
不是"精算"。`xG 回归信号`同理，只提示，不改推荐。

**7. 每分钟提交一次，`.git` 会长得很快。**
每次提交只带一份 `official_matches.json`（2026-10-22 起不再双写
`matches_34.json`）。如果嫌大，把数据文件改成每天提交一次、代码随时提交。

**8. 排查看 `sync_live.log`。**
pythonw 没有控制台，所有关键事件、git push 返回码、未捕获异常都落在这个文件
（超过 2MB 自动轮转为 `.1`）。sfc 的日志在 `sfc_sync.log`。

---

## 七、本地备份

- `_archive_local/`：调试截图、旧图片、`.bak` 快照（9MB，不进版本库，可随时删）
- Telegram 情报引擎在另一个仓库：`E:\telegram_football_monitor`
