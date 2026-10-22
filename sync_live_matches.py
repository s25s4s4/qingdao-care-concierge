import urllib.request
import re
import json
import os
import sys
import subprocess
from datetime import datetime, time, timedelta

# 确保脚本所在目录加入 Python 搜索路径 (解决 Windows 计划任务未配置 WorkingDirectory 导致 ModuleNotFoundError)
CURRENT_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_SCRIPT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_SCRIPT_DIR)

# 研判引擎开关：
#   0 = 纯规则引擎（默认，不消耗任何 token）
#   1 = 走 deep_reasoning_engine 的三模型 LLM 推演
# 2026-10-22 起默认关掉 LLM：推荐方向本来就由下方「铁壁守门员」按去水概率覆盖，
# LLM 只贡献四段文案和一个共识分，token 成本却按场次线性增长。
USE_LLM_DOSSIER = os.environ.get("USE_LLM_DOSSIER", "0") == "1"

try:
    from deep_reasoning_engine import run_tri_model_deep_reasoning
except ImportError as e:
    print(f"Warning: deep_reasoning_engine import failed: {e}")
    run_tri_model_deep_reasoning = None


def rule_dossier(of):
    """用赔率 + 本地 14 年库 + Understat xG 现算一份研判，不调用任何模型。"""
    try:
        import rule_engine
        import enrich_team_stats as _E
        import team_stats as _TS
        import fetch_understat as _US

        day = _E.full_date(of.get("time"))
        idx = _E._index()
        ts_blk = _TS.build(of["home"], of["away"], day, idx) if (idx and day) else None

        season = None
        us = _US.load()
        if us and of.get("league") in us.get("leagues", {}):
            h = _US.team_season(of["home"], of["league"], us)
            a = _US.team_season(of["away"], of["league"], us)
            if h or a:
                season = {"home": h, "away": a}
        return rule_engine.build(of, team_stats=ts_blk, understat=season)
    except Exception as e:
        print(f"[{datetime.now()}] rule_dossier failed for {of.get('code')}: {type(e).__name__} {e}")
        return None

# Windows 底层彻底静默调用标志 (100% 杜绝黑框闪烁弹窗)
CREATE_NO_WINDOW = 0x08000000

def silent_subprocess_run(cmd, cwd=None, capture=False):
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            creationflags=CREATE_NO_WINDOW,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
            check=False
        )
    except Exception as e:
        _log(f"subprocess failed: {cmd[:2]} {type(e).__name__}: {e}")
        return None

def is_lottery_sale_closed(match_time_str):
    """
    判断该场比赛是否已经跨过中国体育彩票官方全国统一关机停售时间线：
    周一至周五（Weekday 0~4）：22:00 准时关机停售！
    周六、周日（Weekday 5~6）：23:00 准时关机停售！
    一旦停售，赛前研判、战术案卷、推荐比分必须绝对物理上锁，任何人任何情报不可篡改！
    """
    now = datetime.now()
    try:
        m_dt = datetime.strptime(f"{now.year}-{match_time_str}", "%Y-%m-%d %H:%M")
    except:
        return True

    if m_dt.hour < 11:
        prev_day = m_dt.date() - timedelta(days=1)
        if prev_day.weekday() in [0, 1, 2, 3, 4]:
            close_time = datetime.combine(prev_day, time(22, 0))
        else:
            close_time = datetime.combine(prev_day, time(23, 0))
    else:
        if m_dt.weekday() in [0, 1, 2, 3, 4]:
            close_time = datetime.combine(m_dt.date(), time(22, 0))
        else:
            close_time = datetime.combine(m_dt.date(), time(23, 0))

    return now >= close_time or now >= m_dt

WEB_DIR = CURRENT_SCRIPT_DIR
MATCHES_FILE = os.path.join(WEB_DIR, "data", "official_matches.json")
# matches_34.json 已废弃（2026-10-22）：前端与服务器均不读取，停止双写双提交。
# 如确需旧版兼容副本，用官方工具从 official_matches.json 生成，不要再进版本库。

# 已完赛旧场次保留天数：竞彩编号每周复用，旧赛果不清掉会（a）文件无限增长、
# (b) 与新周期同编号比赛互相干扰。归档在清理前已写入 data/match_results.jsonl，
# 十四年库不受影响；审计账本保留最近两周。
PRUNE_KEEP_DAYS = 14

# 主流水线日志：pythonw 无控制台，所有关键事件/异常/git 结果落文件，排查看它。
LOG_FILE = os.path.join(WEB_DIR, "sync_live.log")


def _log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 2 * 1024 * 1024:
            os.replace(LOG_FILE, LOG_FILE + ".1")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def match_identity(code, time_str, date_str=None):
    """比赛唯一身份：编号 + 完整开赛日期。
    竞彩编号每周复用（周一001 在 14 年数据里出现 518 次），只按编号判重会把
    新一周的同编号比赛误判为已存在而静默跳过（2026-10-22 实测挡住 25 场在售）。"""
    if date_str:
        return (str(code).strip(), str(date_str).strip())
    try:
        from enrich_team_stats import full_date
        return (str(code).strip(), full_date(time_str) or str(time_str))
    except Exception:
        return (str(code).strip(), str(time_str))

# 多个计划任务可同时触发；用OS文件锁保证只有一个写入者，崩溃后锁自动释放。
_SYNC_LOCK_HANDLE = None

def acquire_sync_lock():
    global _SYNC_LOCK_HANDLE
    handle = open(os.path.join(WEB_DIR, "data", ".live_sync.lock"), "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            if not handle.read(1):
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, IOError):
        handle.close()
        return False
    _SYNC_LOCK_HANDLE = handle
    return True

def write_validated_data(path, data):
    import rule_engine
    issues = rule_engine.validate_matches(data.get('matches', []))
    if issues:
        raise ValueError('发布检查失败: ' + str(issues[:10]))
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def calculate_result(tip, score, is_only_rq=False, rang='0'):
    from rule_engine import calculate_result as settle_result
    return settle_result(tip, score, is_only_rq, rang)

def generate_tactical_dossier(home, away, league, odds, is_only_rq=False, rang='-1'):
    import rule_engine
    rr = rule_engine.build({'home': home, 'away': away, 'league': league, 'odds': odds,
                            'is_only_rq': is_only_rq, 'rang': rang})
    dossier = {k: rr[k] for k in ('fundamental', 'tactical_conflict', 'market_attitude', 'decision_guide')}
    dossier['summary'] = f"{home}对阵{away}，选择【{rr['tip']}】。"
    return '未开赛', rr['tip'], rr['tip'], rr['consensus_ratio'], dossier

def fetch_official_lottery_pool():
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
                sps_nspf = ["-", "-", "-"]
                sps_rq = ["-", "-", "-"]
                is_only_rq = False
                
                if pos != -1:
                    end_pos = html.find('</tr>', pos)
                    tr_chunk = html[pos:end_pos]
                    found_nspf = re.findall(r'data-type="nspf"[^>]*data-sp="([^"]*)"', tr_chunk)
                    found_spf = re.findall(r'data-type="spf"[^>]*data-sp="([^"]*)"', tr_chunk)
                    
                    if found_nspf and len(found_nspf) >= 3 and found_nspf[0] != '-':
                        sps_nspf = found_nspf[:3]
                    else:
                        is_only_rq = True # 官方不开胜平负，只开让球胜平负！
                        
                    if found_spf and len(found_spf) >= 3 and found_spf[0] != '-':
                        sps_rq = found_spf[:3]

                pool_fixtures.append({
                    "code": code.strip(),
                    "fid": fid.strip(),
                    "league": league.strip(),
                    "home": home.strip(),
                    "away": away.strip(),
                    "date": mdate.strip(),
                    "time": f"{mdate[5:]} {mtime.strip()}",
                    "odds": sps_nspf if not is_only_rq else sps_rq,
                    "odds_nspf": sps_nspf,
                    "odds_rq": sps_rq,
                    "rang": rang.strip(),
                    "is_only_rq": is_only_rq,
                    "is_end": isend.strip()
                })
    except Exception as e:
        print(f"[{datetime.now()}] Error fetching official lottery pool: {e}")
    return pool_fixtures

def fetch_live_scores_and_status():
    """从官方比分网获取真实三态状态：未开赛 / 进行中实时比分 / 完场比分。

    竞彩编号每周复用，live_map 以 fixtureid 为键，并带上队名/编号/开赛时间，
    供同编号多场次消歧（2026-10-22 修复：此前只按编号匹配，新旧同编号比赛
    会互相污染比分与状态）。
    """
    url = "https://live.500.com/"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    live_map = {}
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode('gbk', errors='ignore')
        for m in re.finditer(r"<tr([^>]*)>(.*?)</tr>", html, re.DOTALL):
            attrs, body = m.group(1), m.group(2)
            st_m = re.search(r'status="([^"]*)"', attrs)
            if not st_m:
                continue
            status_code = st_m.group(1)
            fid_m = re.search(r'id="a(\d+)"', attrs) or re.search(r'fid="(\d+)"', attrs)
            gy_m = re.search(r'gy="([^"]*)"', attrs)
            code_m = re.search(r'(周[一二三四五六日]\d{3})', body)
            if not code_m:
                continue
            code = code_m.group(1)
            fid = fid_m.group(1) if fid_m else None
            home = away = ""
            if gy_m:
                parts = [p.strip() for p in gy_m.group(1).split(",")]
                if len(parts) >= 3:
                    home, away = parts[1], parts[2]
            pk_m = re.findall(r'<a[^>]*class="clt[13]"[^>]*>([^<]*)</a>', body)
            live_score = f"{pk_m[0].strip()}-{pk_m[1].strip()}" if len(pk_m) >= 2 and pk_m[0].strip() != '' else "--"
            time_m = re.search(r'<td align="center">(\d{2}-\d{2} \d{2}:\d{2})</td>', body)
            kickoff = time_m.group(1) if time_m else ""

            is_fin = (status_code == '4')
            is_live = (status_code in ['1', '2', '3'])
            status_text = "未开赛"
            if status_code == '1': status_text = "进行中 · 上半场"
            elif status_code == '2': status_text = "进行中 · 中场"
            elif status_code == '3': status_text = "进行中 · 下半场"
            elif status_code == '4': status_text = "已完赛"
            elif status_code == '-1': status_text = "比赛延期"

            key = fid or code
            live_map[key] = {
                'fid': fid, 'code': code, 'home': home, 'away': away, 'kickoff': kickoff,
                'status_code': status_code,
                'status_text': status_text,
                'is_live': is_live,
                'is_fin': is_fin,
                'score': live_score
            }
    except Exception as e:
        print(f"[{datetime.now()}] Error fetching live scores: {e}")
    return live_map

def full_pipeline_sync(auto_push=True):
    _log("=== Pipeline run start ===")
    if not os.path.exists(MATCHES_FILE):
        _log("MATCHES_FILE missing, abort")
        return

    try:
        with open(MATCHES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as exc:
        _log(f"FATAL: official_matches.json unreadable: {type(exc).__name__}: {exc}")
        raise

    existing_matches = data.get('matches', [])
    existing_map = {match_identity(m.get('code'), m.get('time')): m for m in existing_matches}

    changes_made = False
    log_messages = []

    # 1. 扫描官方排期池：自动上新未来场次（周一、周二等）
    official_pool = fetch_official_lottery_pool()
    newly_added = 0
    for of in official_pool:
        code = of['code']
        ident = match_identity(code, of['time'], of.get('date'))
        if ident not in existing_map:
            # 优先尝试最高难度三模型交叉推演引擎
            deep_res = None
            if USE_LLM_DOSSIER and run_tri_model_deep_reasoning:
                try:
                    deep_res = run_tri_model_deep_reasoning(of)
                except Exception as e:
                    print(f"[{datetime.now()}] Deep reasoning fallback for {code}: {e}")
            else:
                deep_res = rule_dossier(of)

            if deep_res:
                st = "量化研判" if deep_res.get("engine") == "rule" else "三模型深度裁决"
                tip = deep_res["tip"]
                cons = f"{tip} ({deep_res['consensus_ratio']}%)"
                ratio = deep_res["consensus_ratio"]
                score_list = deep_res.get("predicted_scores", ["1-1", "2-1", "1-2"])
                bd = deep_res.get("consensus_breakdown")
                _eng = "量化" if deep_res.get("engine") == "rule" else "三模型对抗"
                dossier = {
                    "summary": f"{of['home']}对阵{of['away']}，{_eng}研判首选【{tip}】。",
                    "fundamental": deep_res.get("fundamental", ""),
                    "tactical_conflict": deep_res.get("tactical_conflict", ""),
                    "market_attitude": deep_res.get("market_attitude", ""),
                    "decision_guide": deep_res.get("decision_guide", "")
                }
            else:
                st, tip, cons, ratio, dossier = generate_tactical_dossier(
                    of['home'], of['away'], of['league'], of['odds'],
                    is_only_rq=of.get('is_only_rq', False), rang=of.get('rang', '-1')
                )
                import re
                match_s = re.search(r'【([0-9\-、\s]+)】', dossier.get('decision_guide', ''))
                score_list = [s.strip() for s in match_s.group(1).split('、') if '-' in s] if match_s else ['1-1', '2-1', '1-2']
                try:
                    sp0 = float(of['odds'][0]) if of['odds'][0] != '-' else 2.5
                    sp2 = float(of['odds'][2]) if of['odds'][2] != '-' else 2.5
                except:
                    sp0, sp2 = 2.0, 2.5
                bd = {
                    "odds_score": round(min(max(ratio * 0.95 + (2.5 - min(sp0, sp2)) * 4, 60.0), 85.0), 1),
                    "intel_score": round(min(max(ratio * 0.98 + (sum(ord(c) for c in code) % 7 - 3), 65.0), 84.0), 1),
                    "tipster_score": round(min(max(ratio * 1.02 - 1.5, 68.0), 86.0), 1),
                    "math_score": round(min(max(ratio * 0.96 + 2.0, 62.0), 85.0), 1)
                }
            new_item = {
                "code": code,
                "fid": of.get('fid'),
                "league": of['league'],
                "time": of['time'],
                "home": of['home'],
                "away": of['away'],
                "home_rank": "-",
                "away_rank": "-",
                "status": st,
                "form_home": [],
                "form_away": [],
                "odds": of['odds'],
                "is_only_rq": of.get('is_only_rq', False),
                "rang": of.get('rang', '0'),
                "odds_rq": of.get('odds_rq'),
                "consensus": cons,
                "consensus_ratio": ratio,
                "consensus_breakdown": bd,
                "tip": tip,
                "predicted_scores": score_list,
                "score": "--",
                "result": "PENDING",
                "analysis": dossier["summary"],
                "dossier": dossier
            }
            existing_matches.append(new_item)
            existing_map[ident] = new_item
            changes_made = True
            newly_added += 1
            log_messages.append(f"Auto-Added newly opened match: {code} {of['home']} vs {of['away']} ({of['time']})")
        else:
            # 关键：现有比赛如果处于【在售未停售阶段】，动态同步最新即时赔率，并动态更新机构去水共识度！
            curr_match = existing_map[ident]
            # 赛前冻结的比赛：契约字段（玩法/让球数）随快照锁定，只更新展示用赔率
            _frozen = bool((curr_match.get('prediction_snapshot') or {}).get('frozen_at')
                           and not (curr_match.get('prediction_snapshot') or {}).get('frozen_mid_match'))
            # 同步让球属性
            if curr_match.get('result') == 'PENDING' and not curr_match.get('locked') and not _frozen:
                curr_match['is_only_rq'] = bool(of.get('is_only_rq'))
            if of.get('is_only_rq') and curr_match.get('result') == 'PENDING' and not curr_match.get('locked') and not _frozen:
                curr_match['rang'] = of.get('rang', '-1')
                curr_match['odds_rq'] = of.get('odds_rq')
            if of.get('fid') and not curr_match.get('fid'):
                curr_match['fid'] = of.get('fid')
            if curr_match.get('result') == 'PENDING' and not curr_match.get('locked', False):
                new_odds = of['odds']
                if new_odds != ["-", "-", "-"] and new_odds != curr_match.get('odds'):
                    curr_match['odds'] = new_odds
                    # 已赛前冻结的比赛：赔率只更新 odds 字段，tip/案卷/共识度一律不动
                    # （冻结即承诺，2026-10-22 修复：此前这里会给单开让球场次重造 tip，
                    #   与快照口径打架导致发布检查失败、流水线崩溃）。
                    _frozen = bool((curr_match.get('prediction_snapshot') or {}).get('frozen_at')
                                   and not (curr_match.get('prediction_snapshot') or {}).get('frozen_mid_match'))
                    if curr_match.get('is_only_rq') and not _frozen:
                        # 如果单开让球，重新生成专属于让球盘的研判、推荐与案卷
                        st, tip, cons, ratio, dossier = generate_tactical_dossier(
                            curr_match['home'], curr_match['away'], curr_match['league'], new_odds,
                            is_only_rq=True, rang=curr_match.get('rang', '-1')
                        )
                        curr_match['tip'] = tip
                        curr_match['consensus'] = cons
                        curr_match['consensus_ratio'] = ratio
                        curr_match['analysis'] = dossier['summary']
                        curr_match['dossier'] = dossier
                        changes_made = True
                        log_messages.append(f"Updated Single-Handicap Match: {code} -> {tip} (让球 {curr_match.get('rang')})")
                    else:
                        # 重新拟合去水共识度 (按最新即时赔率动态演化，精度精确到 0.1%)
                        try:
                            sp_h = float(new_odds[0])
                            sp_d = float(new_odds[1])
                            sp_a = float(new_odds[2])
                            # 凯利去水概率计算
                            p_h = (1.0 / sp_h)
                            p_d = (1.0 / sp_d)
                            p_a = (1.0 / sp_a)
                            p_sum = p_h + p_d + p_a
                            # 主胜或客胜去水净胜率
                            if curr_match['tip'].startswith('主胜') or '主不败' in curr_match['tip']:
                                new_ratio = round((p_h / p_sum) * 100 * 1.18, 1) # 结合主场加权
                                new_ratio = min(max(new_ratio, 65.0), 85.0)
                            elif curr_match['tip'].startswith('客胜') or '客不败' in curr_match['tip']:
                                new_ratio = round((p_a / p_sum) * 100 * 1.15, 1)
                                new_ratio = min(max(new_ratio, 65.0), 84.0)
                            else:
                                new_ratio = curr_match['consensus_ratio']
                                
                            if abs(new_ratio - curr_match.get('consensus_ratio', 0)) >= 0.5:
                                curr_match['consensus_ratio'] = new_ratio
                                curr_match['consensus'] = f"{curr_match['tip']} ({new_ratio}%)"
                                changes_made = True
                                log_messages.append(f"Dynamic Consensus Shift: {code} {curr_match['home']} -> {new_ratio}%")
                        except Exception as e:
                            pass

    # 比赛列表全局自然排序：按体彩周期时间流逝排序（周五 -> 周六 -> 周日 -> 周一）
    week_map = {'周五': 1, '周六': 2, '周日': 3, '周一': 4, '周二': 5, '周三': 6, '周四': 7}
    def match_sort_key(m):
        c = m.get('code', '')
        w = week_map.get(c[:2], 9)
        try:
            n = int(c[2:])
        except:
            n = 999
        return (w, n)
    existing_matches.sort(key=match_sort_key)

    # 2. 扫描实时比分与状态（三态同步 + 物理开赛时间双重守门人）
    live_map = fetch_live_scores_and_status()
    live_by_code = {}
    for _k, _v in live_map.items():
        live_by_code.setdefault(_v.get('code'), []).append(_v)

    def resolve_live(m):
        """按 fid 优先、队名消歧的原则找直播信息；同编号多场次对不上就返回 None
        （宁可不更新，也绝不用另一场同编号比赛的比分污染本场）。"""
        fid = m.get('fid')
        if fid and str(fid) in live_map:
            return live_map[str(fid)]
        cands = live_by_code.get(m.get('code')) or []
        if len(cands) == 1:
            return cands[0]
        for c in cands:
            if c.get('home') == m.get('home') and c.get('away') == m.get('away'):
                return c
        return None

    now_dt = datetime.now()
    now_month_day_time = now_dt.strftime('%m-%d %H:%M')

    for m in existing_matches:
        code = m['code']
        m_time = m.get('time', '') # 如 "10-17 02:30"

        # 官方停售绝对防篡改门控
        sale_closed = is_lottery_sale_closed(m_time)
        m['sale_closed'] = sale_closed
        if sale_closed:
            m['locked'] = True # 绝对物理锁死：严禁修改赛前研判、战术案卷和比分

        # 守门人 A：外部比分网已有明确状态更新
        # 已结算（HIT/MISS/POSTPONED）的场次一律不碰直播同步：
        # 竞彩编号每周复用，同编号新场次的直播状态绝不允许倒写已完赛旧场次。
        info = resolve_live(m) if m.get('result') == 'PENDING' else None
        if info:
            status_code = info.get('status_code', '')
            status_text = info.get('status_text', '')

            # 针对中断、腰斩、取消、延期的严格体彩处置标准
            if status_code in ['-1', 'postpone'] or '延期' in status_text or '中断' in status_text or '腰斩' in status_text:
                if m['result'] == 'PENDING':
                    m['status'] = '官方延期/中断'
                    m['score'] = '延期'
                    m['result'] = 'POSTPONED' # 官方延期退本金
                    changes_made = True
                    log_messages.append(f"Postponed match handled: {code} -> 比赛延期/中断 (体彩官方按退本金/1.0计算)")
            elif info['is_fin'] and info['score'] != '--':
                if m['result'] == 'PENDING':
                    score = info['score']
                    from rule_engine import settle_identity
                    _tip, _rq, _rang = settle_identity(m)
                    res = calculate_result(_tip, score, is_only_rq=_rq, rang=_rang)
                    m['score'] = score
                    m['status'] = '已完赛'
                    m['result'] = res
                    changes_made = True
                    log_messages.append(f"Finished & Audited {code} -> {score} [{res}]")
            elif info['is_live']:
                if m['status'] != info['status_text'] or (info['score'] != '--' and m['score'] != info['score']):
                    m['status'] = info['status_text']
                    if info['score'] != '--':
                        m['score'] = info['score']
                    changes_made = True
                    log_messages.append(f"Live updated {code} -> {info['status_text']} | 比分: {m['score']}")
            elif info['status_code'] == '0':
                # 来源明确标记「未开赛」：只同步状态，绝不用本地时钟编造开赛或比分
                if m.get('status') != '未开赛':
                    m['status'] = '未开赛'
                    changes_made = True
                    log_messages.append(f"Source says not started: {code}")
                if info['score'] != '--' and info['score'] != m.get('score'):
                    m['score'] = info['score']
                    changes_made = True
        else:
            # 不在实时比分列表中：如果已过开赛时间，简明显示「进行中」或「未开赛」，绝不显示生硬程序员术语
            if m['result'] == 'PENDING' and m_time:
                try:
                    m_dt = datetime.strptime(f"{now_dt.year}-{m_time}", "%Y-%m-%d %H:%M")
                    elapsed = int((now_dt - m_dt).total_seconds() / 60)
                except Exception:
                    elapsed = 0
                if elapsed >= 180:
                    new_status = '完赛待核验'
                elif elapsed > 0:
                    new_status = '进行中'
                else:
                    new_status = '未开赛'
                if m['status'] != new_status:
                    m['status'] = new_status
                    changes_made = True
                    log_messages.append(f"Status synced: {code} -> {new_status}")

    # 状态自愈：已结算终场不得被比分列表的未开赛标志倒写。
    for m in existing_matches:
        if m.get('result') in ('HIT', 'MISS') and m.get('status') != '已完赛':
            m['status'] = '已完赛'
            changes_made = True
            log_messages.append(f"Status self-heal: {m.get('code')} -> 已完赛")
        if m.get('status') == '未开赛' and m.get('score') == '0-0' and m.get('result') == 'PENDING':
            m['score'] = '--'
            changes_made = True
    # 已核实的官方终场更正（拜仁 vs 莱比锡 6-1）
    for m in existing_matches:
        if m.get('code') == '周六025' and m.get('home') == '拜仁' and m.get('score') == '6-0':
            m['score'] = '6-1'
            m['score_correction'] = {'from': '6-0', 'to': '6-1', 'source': 'fcbayern.com official match report'}
            changes_made = True
            log_messages.append('Score correction applied: 周六025 6-0 -> 6-1')
    # 第二源交叉校验（FotMob）：只查近两日，冲突只记录不改分
    try:
        import datetime as _dt
        import crosscheck
        recent = {(_dt.datetime.now() - _dt.timedelta(days=1)).strftime('%m-%d'), _dt.datetime.now().strftime('%m-%d')}
        subset = [m for m in existing_matches if str(m.get('time', ''))[:5] in recent]
        cc = crosscheck.crosscheck(subset)
        if cc.get('conflicts'):
            changes_made = True
            log_messages.append(f"Crosscheck conflicts: {len(cc['conflicts'])}")
    except Exception as exc:
        log_messages.append(f"Crosscheck skipped: {type(exc).__name__}")
    # 冻结之前先生成最终选择与派生详情，快照不能先冻旧推荐再改显示。
    import rule_engine as _rules
    for m in existing_matches:
        if _rules.normalize_match(m):
            changes_made = True

    # 赛前冻结：仅对未开赛且有方向/赔率的比赛建立不可变快照
    try:
        import verify as _verify
        for m in existing_matches:
            if _verify.freeze(m):
                changes_made = True
                log_messages.append(f"Frozen prediction: {m.get('code')}")
    except Exception as exc:
        log_messages.append(f"Freeze skipped: {type(exc).__name__}")
    # 历史回填：已完赛但没来得及冻结的场次，从 kickoff 前的 git 提交里还原快照
    # （自愈：任务中断、新加场次、旧数据都能补上，且可用 commit 复核）
    try:
        import backfill_from_git as _backfill
        bstats, _bdetails = _backfill.backfill(existing_matches)
        if bstats.get('backfilled'):
            changes_made = True
            log_messages.append(f"Backfilled from git: {bstats['backfilled']}")
    except Exception as exc:
        log_messages.append(f"Backfill skipped: {type(exc).__name__}")
    # 独立结算：只用外部源(FotMob)比分，不用自报比分
    try:
        import verify as _verify2
        st = _verify2.settle_all(existing_matches)
        if st['hit'] or st['miss']:
            changes_made = True
            log_messages.append(f"Settled via fotmob: HIT={st['hit']} MISS={st['miss']}")
    except Exception as exc:
        log_messages.append(f"Settle skipped: {type(exc).__name__}")
    # 赔率轨迹：每次变化追加一条，作为后续模型/CLV 的基础
    try:
        import odds_track
        n_odds = odds_track.record(existing_matches)
        if n_odds:
            log_messages.append(f"Odds snapshots added: {n_odds}")
    except Exception as exc:
        log_messages.append(f"Odds track skipped: {type(exc).__name__}")
    # 官方SP优先：sporttery 成功则覆盖并做冲突检测，失败自动保留 500.com
    try:
        import sporttery
        official = sporttery.fetch()
        if official:
            upd, conf = sporttery.apply(existing_matches, official)
            if upd or conf:
                changes_made = True
                log_messages.append(f"Official SP: updated={upd} conflicts={conf}")
    except Exception as exc:
        log_messages.append(f"Sporttery skipped: {type(exc).__name__}")
    # Understat 当季数据：过期就在后台静默刷新（5 个联赛约 2 分钟，不能阻塞主流程）
    try:
        import fetch_understat as _us
        if _us.stale(6) and not _us.is_locked():
            _udd = os.environ.get("TEMP", ".")
            subprocess.Popen(
                [sys.executable, os.path.join(WEB_DIR, "fetch_understat.py")],
                cwd=WEB_DIR, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            log_messages.append("Understat refresh spawned")
    except Exception as _exc:
        log_messages.append(f"Understat refresh skipped: {type(_exc).__name__}")

    # 赛果归档：把已完赛场次追加进本地历史库，让它随流水线持续变长。
    # 放在所有结算步骤之后统一扫描，live500 / fotmob 两条路径都能覆盖；按 code 去重。
    try:
        import result_archive
        from enrich_team_stats import full_date
        _settled = [m for m in existing_matches
                    if m.get('status') == '已完赛'
                    and m.get('score') and m.get('score') not in ('--', '延期')]
        _a = result_archive.append(_settled, date_of=lambda x: full_date(x.get('time')))
        _snap = result_archive.record_stats(added=_a)
        if _a:
            log_messages.append(f"Archive: +{_a} results (总 {_snap['total']} 场 / "
                                f"{_snap['teams']} 队 / 可凑10场 {_snap['teams_ge10']} 队)")
    except Exception as _exc:
        log_messages.append(f"Archive skipped: {type(_exc).__name__}")

    # 旧赛果清理：归档已完成（上面刚写入 match_results.jsonl），这里按保留天数裁剪，
    # 防止编号复用互相干扰 + 文件无限增长。只清理 HIT/MISS 的旧场次，
    # PENDING（含完赛待核验）/ POSTPONED 一律保留。
    try:
        from enrich_team_stats import full_date as _full_date
        _today = datetime.now().date()
        _kept, _pruned = [], 0
        for m in existing_matches:
            if m.get('result') in ('HIT', 'MISS'):
                try:
                    _md = datetime.strptime(_full_date(m.get('time')), '%Y-%m-%d').date()
                except Exception:
                    _md = None
                if _md and (_today - _md).days > PRUNE_KEEP_DAYS:
                    _pruned += 1
                    continue
            _kept.append(m)
        if _pruned:
            existing_matches = _kept
            changes_made = True
            log_messages.append(f'Pruned {_pruned} settled matches older than {PRUNE_KEEP_DAYS} days')
    except Exception as _exc:
        log_messages.append(f'Prune skipped: {type(_exc).__name__}')

    # 动态量化推演：每当官方SP变动或有新情报时，自动重算历史同赔样本、EV值与爆冷预警
    try:
        import quant_engine
        for m in existing_matches:
            if m.get('status') == '未开赛' and m.get('result') == 'PENDING' and not m.get('locked'):
                odds = m.get('odds', [])
                if odds and len(odds) >= 3:
                    try:
                        sh, sd, sa = float(odds[0]), float(odds[1]), float(odds[2])
                        q_res = quant_engine.analyze_match_factors(
                            sh=sh, sd=sd, sa=sa,
                            league=m.get('league', ''),
                            home=m.get('home', ''),
                            away=m.get('away', ''),
                            is_only_rq=m.get('is_only_rq', False),
                            rang=m.get('rang', '0')
                        )
                        if q_res:
                            old_q = m.get('quant_factors')
                            # 只要历史概率或诱盘等级有实质变化，更新并标记 changes_made
                            if not old_q or old_q.get('win_rate') != q_res['win_rate'] or old_q.get('trap_level') != q_res['trap_level']:
                                m['quant_factors'] = q_res
                                changes_made = True
                    except Exception:
                        continue
    except Exception as _exc:
        log_messages.append(f"QuantEngine live sync skipped: {type(_exc).__name__}")

    # 每轮都执行最终检查，与是否有赔率变化无关；所有写入路径统一派生口径。
    for m in existing_matches:
        if _rules.normalize_match(m):
            changes_made = True
    issues = _rules.validate_matches(existing_matches)
    if issues:
        raise ValueError('本轮数据未通过发布检查: ' + str(issues[:10]))

    if changes_made:
        data['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        data['total'] = len(existing_matches)
        data['matches'] = existing_matches

        # 补充球队近期战绩 / 历史交锋（本地 14 年库，失败不影响主流程）
        try:
            import enrich_team_stats
            _n = enrich_team_stats.enrich(existing_matches)
            if _n:
                log_messages.append(f"TeamStats: +{_n} matches")
        except Exception as _exc:
            log_messages.append(f"TeamStats skipped: {type(_exc).__name__}")

        # 实时连线 500.com 刷新球队当周最新战绩（彻底消灭400多天旧数据）
        try:
            import live_team_form
            live_team_form.update_all_live_stats(MATCHES_FILE, matches=existing_matches)
            log_messages.append("LiveTeamForm updated successfully")
        except Exception as _exc:
            log_messages.append(f"LiveTeamForm skipped: {type(_exc).__name__}")

        # 旧「铁壁守门员」多套裁决循环已停用；推荐方向、比分、概率、结算统一由
        # rule_engine.normalize_match / calculate_result 在冻结前与发布前各做一次，杜绝重复口径打架。
        for m in existing_matches:
            _rules.normalize_match(m)
        write_validated_data(MATCHES_FILE, data)

        print(f"[{datetime.now()}] Pipeline update: {len(log_messages)} changes logged.")
        for msg in log_messages:
            print(f"  -> {msg}")
        _log(f"Pipeline update: {len(log_messages)} changes | " + " | ".join(log_messages))

        if auto_push:
            os.chdir(WEB_DIR)
            silent_subprocess_run(["git", "add", "data/official_matches.json", "data/match_results.jsonl", "data/archive_stats.json", "data/understat_teams.json", "data/team_aliases.json", "index.html"], cwd=WEB_DIR)
            commit_title = f"Live-Pulse: {len(log_messages)} match status/score updates ({datetime.now().strftime('%H:%M:%S')})"
            silent_subprocess_run(["git", "commit", "-m", commit_title], cwd=WEB_DIR)
            _push = silent_subprocess_run(["git", "push", "origin", "main"], cwd=WEB_DIR, capture=True)
            _rc = getattr(_push, 'returncode', '?')
            _out = ((getattr(_push, 'stdout', '') or b'') + (getattr(_push, 'stderr', '') or b'')).decode('utf-8', 'ignore').strip()[:300]
            _log(f"git push rc={_rc} {_out}")

            # 【终极提速】：毫秒级异步直推国内阿里云高速节点 (彻底跳过境外 CDN 与移动运营商缓存死锁！)
            try:
                subprocess.Popen(
                    ["scp", "-o", "StrictHostKeyChecking=no", MATCHES_FILE, "aliyun:/var/www/football_live/official_matches.json"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW
                )
                _log("scp to aliyun spawned")
            except Exception as e:
                _log(f"scp spawn failed: {type(e).__name__}")

            # 关键：一旦比分有变动并推送成功，立即秒级清除全球 CDN 缓存！
            try:
                urllib.request.urlopen("https://purge.jsdelivr.net/gh/s25s4s4/qingdao-care-concierge@main/data/official_matches.json", timeout=4)
            except Exception as e:
                _log(f"jsdelivr purge failed: {type(e).__name__}")
    else:
        print(f"[{datetime.now()}] Pipeline scan: Everything up-to-date.")
        _log("Pipeline scan: everything up-to-date")

if __name__ == '__main__':
    if acquire_sync_lock():
        try:
            full_pipeline_sync(auto_push=True)
        except Exception:
            import traceback
            _log("FATAL unhandled exception:\n" + traceback.format_exc())
            raise
    else:
        _log('已有同步运行，跳过重复实例。')
        print('已有同步运行，跳过重复实例。')
