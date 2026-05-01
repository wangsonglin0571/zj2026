"""
WxPusher 推送模块 — 浙江争冠页比赛更新推送到微信
从 tech_feed 共享配置读取 token
"""
import logging, re, sys
from pathlib import Path
import httpx

log = logging.getLogger(__name__)

WXPUSHER_API = "https://wxpusher.zjiecode.com/api/send/message"

# ── 共享配置 ├──
TECH_FEED_CONFIG = Path.home() / "tech_feed" / "config.py"


def _read_config():
    """从 tech_feed/config.py 读取 WxPusher token 和 topic ID"""
    if not TECH_FEED_CONFIG.exists():
        log.error(f"配置文件不存在: {TECH_FEED_CONFIG}")
        return None, None
    src = TECH_FEED_CONFIG.read_text(encoding="utf-8")
    tok = re.search(r'WXPUSHER_APP_TOKEN\s*=\s*["\']([^"\']+)["\']', src)
    tid = re.search(r'WXPUSHER_TOPIC_ID\s*=\s*(\d+)', src)
    if not tok or not tid:
        log.error("配置文件中未找到 WxPusher token 或 topic ID")
        return None, None
    app_token = tok.group(1)
    topic_id = int(tid.group(1))
    if app_token == "***":
        log.error("WxPusher token 未配置 (config.py 中为 ***)")
        return None, None
    return app_token, topic_id


def push_match_report(summary: str) -> bool:
    """推送比赛报告到 WxPusher"""
    if not summary:
        return True
    return _send("浙江队比赛报告", summary)


def _send(title: str, content: str) -> bool:
    app_token, topic_id = _read_config()
    if not app_token:
        return False

    payload = {
        "appToken": app_token,
        "summary": title[:100],
        "content": content,
        "contentType": 3,
        "topicIds": [topic_id],
        "verifyPay": False,
    }
    try:
        resp = httpx.post(WXPUSHER_API, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 1000:
            return True
        log.error(f"WxPusher 推送失败: {data}")
        return False
    except Exception as e:
        log.error(f"WxPusher 推送异常: {e}")
        return False
