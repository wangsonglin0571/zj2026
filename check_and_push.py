#!/usr/bin/env python3
"""
浙江争冠 — 比赛结果检测 & 报告生成 & 推送

工作流程：
1. 读取当前 data.json
2. 与上一次保存的 state.json 对比，检测是否打完比赛
3. 浙江队比赛结束 → 生成本轮报告 + 下轮预测
4. 本轮所有对手比赛结束 → 补充完整本轮总结
5. 推送到 WxPusher 微信
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

from push import push_match_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# 项目根目录
ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data.json"
STATE_FILE = ROOT / ".state.json"

# DeepSeek API
DEEPSEEK_API_KEY = "sk-f9b43d30fcd9449b97b48323bd6ca297"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-v4-flash"

BEIJING = timezone(timedelta(hours=8))


# ── 状态管理 ──────────────────────────────────────────────


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_current_data() -> dict:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


# ── 变化检测 ──────────────────────────────────────────────


def detect_changes(state: dict, data: dict) -> dict:
    """返回检测到的变化信息"""
    result = {
        "zj_played": False,  # 浙江队本轮是否打完
        "rivals_played": [],  # 本轮已打完的对手
        "all_rivals_done": False,  # 所有对手是否都打完了
        "round": None,
    }

    old_zj = state.get("zhejiang", {})
    new_zj = data.get("zhejiang", {})

    # 检测浙江队比赛
    if old_zj and new_zj:
        old_played = old_zj.get("played", 0)
        new_played = new_zj.get("played", 0)
        if new_played > old_played:
            result["zj_played"] = True
            result["round"] = new_played  # 当前是第几轮

    # 检测对手比赛
    old_rivals = {r["name"]: r for r in state.get("rivals", [])}
    new_rivals = {r["name"]: r for r in data.get("rivals", [])}

    for name, nr in new_rivals.items():
        or_ = old_rivals.get(name, {})
        if or_ and nr.get("played", 0) > or_.get("played", 0):
            result["rivals_played"].append(name)

    if old_rivals and new_rivals:
        old_min = min((r.get("played", 0) for r in state.get("rivals", [])), default=0)
        new_min = min((r.get("played", 0) for r in data.get("rivals", [])), default=0)
        # 所有对手的 played 都增加了，说明本轮结束
        old_total = sum(r.get("played", 0) for r in state.get("rivals", []))
        new_total = sum(r.get("played", 0) for r in data.get("rivals", []))
        num_rivals = len(data.get("rivals", []))
        if num_rivals > 0 and (new_total - old_total) >= num_rivals:
            result["all_rivals_done"] = True

    return result


# ── DeepSeek 报告生成 ─────────────────────────────────────


def build_summary_prompt(data: dict, changes: dict, state: dict) -> str:
    """构建 DeepSeek 提示词"""
    zj = data["zhejiang"]
    next_match = data.get("nextMatch", {})
    rivals = data.get("rivals", [])

    bjt_now = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M")

    # 从 allTeams 获取对手完整信息
    all_teams = {t["name"]: t for t in data.get("allTeams", [])}

    prompt = f"""你是一个中超联赛分析师。现在是北京时间 {bjt_now}。

## 浙江队当前战绩
- 已赛 {zj['played']} 轮
- {zj['wins']}胜 {zj['draws']}平 {zj['losses']}负
- 进球 {zj['gf']} / 失球 {zj['ga']} / 净胜球 {zj['gd']:+d}
- 比赛积分 {zj['gamePts']} / 扣分 {zj['penalty']:+d} / 实际积分 {zj['actual']:+d}

## 竞争对手本轮赛况
"""
    for r in rivals:
        t = all_teams.get(r["name"], {})
        r_played = t.get("played", "?")
        marker = "✅ 已完赛" if r["name"] in changes.get("rivals_played", []) else "⏳"
        prompt += f"- {r['name']}: 已赛{r_played}轮, {r['actual']:+d}分 {marker}\n"

    prompt += f"""
## 下一场比赛
- 对手: {next_match.get('opponent', '待定')}
- 时间: {next_match.get('kickoffBjt', '待定')}
- 地点: {next_match.get('location', '')} {next_match.get('venue', '')}
- 轮次: {next_match.get('note', '')}

## 要求

请用一段话总结本轮浙江队的表现和整个中超形势（约100-150字），内容应包含：
1. 浙江队本轮表现回顾（基于最新数据）
2. 竞争形势变化（和主要竞争对手的积分差变化）
"""

    if changes.get("all_rivals_done"):
        prompt += "3. 本轮全部结束，分析积分榜整体形势\n"

    prompt += f"""
3. 下一场对阵 {next_match.get('opponent', '待定')} 的赛前预测和看点

最后用一句话总结浙江队当前的争冠/保级前景。

要求语气简洁、专业、有洞察力，类似懂球帝的赛后分析风格。纯文本，不加markdown格式，不超过300字。"""

    return prompt


def call_deepseek(prompt: str, max_retries: int = 2) -> str | None:
    """调用 DeepSeek 生成报告"""
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 600,
        "temperature": 0.7,
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    for attempt in range(max_retries + 1):
        try:
            resp = httpx.post(DEEPSEEK_URL, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            log.warning(f"DeepSeek 调用失败 (第{attempt+1}次): {e}")
            if attempt < max_retries:
                time.sleep(2)
    return None


def format_report(summary_text: str, data: dict) -> str:
    """包装成适合微信阅读的 Markdown 格式"""
    zj = data["zhejiang"]
    next_match = data.get("nextMatch", {})
    bjt_now = datetime.now(BEIJING).strftime("%m-%d %H:%M")

    header = (
        f"⚽ **浙江队** · 第 {zj['played']} 轮赛后\n"
        f"📅 {bjt_now}\n\n"
        f"📊 {zj['wins']}胜 {zj['draws']}平 {zj['losses']}负 · "
        f"积 {zj['actual']} 分 (净胜球 {zj['gd']:+d})\n"
        f"📌 下一场: {next_match.get('note', '')} "
        f"{next_match.get('opponent', '待定')}\n\n"
        f"---\n\n"
    )

    if summary_text:
        content = header + summary_text
    else:
        content = header + "暂无分析报告。"
    return content


# ── 主流程 ──────────────────────────────────────────────


def main(dry_run: bool = False):
    state = load_state()
    data = load_current_data()

    if not state:
        log.info("首次运行，保存初始状态")
        _save_full_state(state, data)
        return

    changes = detect_changes(state, data)

    if not changes["zj_played"]:
        log.info("浙江队本轮尚未完赛，跳过推送")
        # 更新状态（确保 rivals 信息是最新的）
        _save_full_state(state, data)
        return

    log.info(
        f"检测到浙江队第 {changes['round']} 轮比赛结束！"
        f" 对手完赛: {changes['rivals_played']}"
        f" 本轮全部结束: {changes['all_rivals_done']}"
    )

    prompt = build_summary_prompt(data, changes, state)
    summary = call_deepseek(prompt)

    if not summary:
        log.error("DeepSeek 报告生成失败，使用简短模板")
        zj = data["zhejiang"]
        summary = (
            f"浙江队本轮赛后：{zj['wins']}胜 {zj['draws']}平 {zj['losses']}负，"
            f"积 {zj['actual']} 分，净胜球 {zj['gd']:+d}。"
            f"下一场对阵 {data['nextMatch'].get('opponent', '待定')}。"
        )

    report = format_report(summary, data)

    if dry_run:
        print("=" * 40)
        print("【模拟推送 - 不实际发送】")
        print(report)
        print("=" * 40)
        return

    # 推送
    ok = push_match_report(report)
    if ok:
        log.info("✅ 推送成功")
    else:
        log.error("❌ 推送失败")

    # 保存新状态
    _save_full_state(state, data)


def _save_full_state(state: dict, data: dict):
    state["last_check"] = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    state["zhejiang"] = {
        "played": data["zhejiang"]["played"],
        "wins": data["zhejiang"]["wins"],
        "draws": data["zhejiang"]["draws"],
        "losses": data["zhejiang"]["losses"],
        "actual": data["zhejiang"]["actual"],
    }
    # 从 allTeams 中提取对手完整信息（含 played）
    all_teams = {t["name"]: t for t in data.get("allTeams", [])}
    state["rivals"] = []
    for r in data.get("rivals", []):
        t = all_teams.get(r["name"], {})
        state["rivals"].append({
            "name": r["name"],
            "played": t.get("played", r.get("played", 0)),
            "actual": r.get("actual", 0),
        })
    save_state(state)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="浙江队比赛结果检测与推送")
    parser.add_argument("--dry-run", action="store_true", help="模拟运行，不推送")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
