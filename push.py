"""
WxPusher 推送模块 — 浙江争冠页比赛更新推送到微信
"""
import logging
import httpx

log = logging.getLogger(__name__)

WXPUSHER_API = "https://wxpusher.zjiecode.com/api/send/message"
APP_TOKEN = "AT_rGHOBbFfxY5H0Kwmuz1kuLdyXV4my5CC"
TOPIC_ID = 44205


def push_match_report(summary: str) -> bool:
    """推送比赛报告到 WxPusher"""
    if not summary:
        return True

    return _send("浙江队比赛报告", summary)


def _send(title: str, content: str) -> bool:
    payload = {
        "appToken": APP_TOKEN,
        "summary": title[:100],
        "content": content,
        "contentType": 3,
        "topicIds": [TOPIC_ID],
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
