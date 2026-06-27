import base64
import hashlib
import hmac
import time
from typing import Dict, Optional

import httpx


def feishu_signature(timestamp: str, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(string_to_sign, b"", digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


async def send_feishu_text(webhook: str, text: str, secret: Optional[str] = None) -> Dict[str, object]:
    payload: Dict[str, object] = {"msg_type": "text", "content": {"text": text}}
    if secret:
        timestamp = str(int(time.time()))
        payload["timestamp"] = timestamp
        payload["sign"] = feishu_signature(timestamp, secret)

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(webhook, json=payload)
        response.raise_for_status()
        return response.json()


async def send_feishu_card(webhook: str, card: Dict[str, object], secret: Optional[str] = None) -> Dict[str, object]:
    payload: Dict[str, object] = {"msg_type": "interactive", "card": card}
    if secret:
        timestamp = str(int(time.time()))
        payload["timestamp"] = timestamp
        payload["sign"] = feishu_signature(timestamp, secret)

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(webhook, json=payload)
        response.raise_for_status()
        return response.json()
