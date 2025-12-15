"""
API 代理模块
处理 Anthropic API 请求并代理到 CodeWhisperer
"""
import asyncio
import json
import logging
import random
import time
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Optional, Tuple

import httpx

from .config import AccountConfig, get_config
from .models import AnthropicRequest, AnthropicResponse
from .request_converter import build_codewhisperer_request, get_message_content
from .response_parser import SSEEvent, collect_full_response, parse_binary_events
from .token_manager import get_token_manager

logger = logging.getLogger(__name__)


def generate_message_id() -> str:
    """生成消息 ID"""
    return f"msg_{datetime.now().strftime('%Y%m%d%H%M%S')}"


async def proxy_request(
    anthropic_req: AnthropicRequest,
    account: AccountConfig,
    retry_on_auth_error: bool = True
) -> Tuple[int, Dict[str, Any], Optional[bytes]]:
    """
    代理请求到 CodeWhisperer

    Args:
        anthropic_req: Anthropic 请求
        account: 账号配置
        retry_on_auth_error: 是否在认证错误时重试

    Returns:
        (状态码, 响应头, 响应体)
    """
    config = get_config()
    token_manager = get_token_manager()

    # 获取 token（自动刷新）
    token = await token_manager.get_token(account)

    # 构建 CodeWhisperer 请求
    cw_request = build_codewhisperer_request(anthropic_req, account)

    # 准备请求头
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token.access_token}",
        "Accept": "application/vnd.amazon.eventstream",
    }

    logger.info(f"Proxying request for account: {account.name}")
    logger.debug(f"CodeWhisperer request: {json.dumps(cw_request, ensure_ascii=False)}")

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                config.api.codewhisperer_url,
                json=cw_request,
                headers=headers
            )

            # 处理认证错误
            if response.status_code == 403 and retry_on_auth_error:
                logger.warning("Got 403, attempting token refresh...")
                token = await token_manager.get_token(account, force_refresh=True)
                headers["Authorization"] = f"Bearer {token.access_token}"

                response = await client.post(
                    config.api.codewhisperer_url,
                    json=cw_request,
                    headers=headers
                )

            return response.status_code, dict(response.headers), response.content

    except httpx.RequestError as e:
        logger.error(f"Request failed: {e}")
        raise


async def handle_non_streaming_request(
    anthropic_req: AnthropicRequest,
    account: AccountConfig
) -> Dict[str, Any]:
    """
    处理非流式请求

    Args:
        anthropic_req: Anthropic 请求
        account: 账号配置

    Returns:
        Anthropic 格式的响应
    """
    status_code, headers, body = await proxy_request(anthropic_req, account)

    if status_code != 200:
        return {
            "error": {
                "type": "api_error",
                "message": f"CodeWhisperer returned status {status_code}: {body.decode('utf-8', errors='replace')}"
            }
        }

    # 解析二进制响应
    events = parse_binary_events(body)
    result = collect_full_response(events)

    # 构建 Anthropic 响应
    config = get_config()
    response = {
        "id": generate_message_id(),
        "type": "message",
        "role": "assistant",
        "content": result["content"],
        "model": anthropic_req.model,
        "stop_reason": result["stop_reason"],
        "stop_sequence": None,
        "usage": {
            "input_tokens": len(get_message_content(anthropic_req.messages[0].content if anthropic_req.messages else "")),
            "output_tokens": result["output_tokens"]
        }
    }

    return response


async def handle_streaming_request(
    anthropic_req: AnthropicRequest,
    account: AccountConfig
) -> AsyncGenerator[str, None]:
    """
    处理流式请求

    Args:
        anthropic_req: Anthropic 请求
        account: 账号配置

    Yields:
        SSE 格式的字符串
    """
    config = get_config()
    message_id = generate_message_id()

    # 发送 message_start 事件
    message_start = {
        "type": "message_start",
        "message": {
            "id": message_id,
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": anthropic_req.model,
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": len(get_message_content(
                    anthropic_req.messages[0].content if anthropic_req.messages else ""
                )),
                "output_tokens": 1,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "service_tier": "standard"
            }
        }
    }
    yield f"event: message_start\ndata: {json.dumps(message_start, ensure_ascii=False)}\n\n"

    # 发送 ping 事件
    yield f"event: ping\ndata: {json.dumps({'type': 'ping'})}\n\n"

    # 发送 content_block_start 事件
    content_block_start = {
        "type": "content_block_start",
        "index": 0,
        "content_block": {
            "type": "text",
            "text": ""
        }
    }
    yield f"event: content_block_start\ndata: {json.dumps(content_block_start, ensure_ascii=False)}\n\n"

    # 代理请求
    try:
        status_code, headers, body = await proxy_request(anthropic_req, account)

        if status_code != 200:
            error_event = {
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": f"CodeWhisperer returned status {status_code}"
                }
            }
            yield f"event: error\ndata: {json.dumps(error_event, ensure_ascii=False)}\n\n"
            return

        # 解析并流式发送事件
        events = parse_binary_events(body)
        output_tokens = 0

        for event in events:
            if not event.event or event.data is None:
                continue

            if event.event == "content_block_delta":
                delta = event.data.get("delta", {})
                if delta.get("type") == "text_delta":
                    output_tokens += len(delta.get("text", ""))

            yield event.to_sse_string()

            # 随机延时模拟流式输出
            await asyncio.sleep(random.uniform(0.05, 0.15))

        # 发送 content_block_stop 事件
        content_block_stop = {
            "type": "content_block_stop",
            "index": 0
        }
        yield f"event: content_block_stop\ndata: {json.dumps(content_block_stop, ensure_ascii=False)}\n\n"

        # 发送 message_delta 事件
        message_delta = {
            "type": "message_delta",
            "delta": {
                "stop_reason": "end_turn",
                "stop_sequence": None
            },
            "usage": {
                "output_tokens": output_tokens
            }
        }
        yield f"event: message_delta\ndata: {json.dumps(message_delta, ensure_ascii=False)}\n\n"

        # 发送 message_stop 事件
        message_stop = {"type": "message_stop"}
        yield f"event: message_stop\ndata: {json.dumps(message_stop, ensure_ascii=False)}\n\n"

    except Exception as e:
        logger.error(f"Streaming request failed: {e}")
        error_event = {
            "type": "error",
            "error": {
                "type": "api_error",
                "message": str(e)
            }
        }
        yield f"event: error\ndata: {json.dumps(error_event, ensure_ascii=False)}\n\n"
