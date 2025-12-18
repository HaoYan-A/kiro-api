"""
API 代理模块
处理 Anthropic API 请求并代理到 CodeWhisperer
支持文件配置和存储系统两种账号来源
"""
import asyncio
import json
import logging
import random
import time
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Optional, Tuple, Union

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

    # 自动获取 profile_arn
    profile_arn = await token_manager.fetch_profile_arn(account)

    # 构建 CodeWhisperer 请求
    cw_request = build_codewhisperer_request(anthropic_req, profile_arn)

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

            # 处理认证错误 (401/403)
            if response.status_code in (401, 403) and retry_on_auth_error:
                logger.warning(f"Got {response.status_code}, attempting token refresh...")
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


async def proxy_request_streaming(
    anthropic_req: AnthropicRequest,
    account: AccountConfig,
    retry_on_auth_error: bool = True
):
    """
    创建流式代理请求

    Args:
        anthropic_req: Anthropic 请求
        account: 账号配置
        retry_on_auth_error: 是否在认证错误时重试

    Returns:
        (client, response): httpx client 和响应对象
    """
    config = get_config()
    token_manager = get_token_manager()

    # 获取 token（自动刷新）
    token = await token_manager.get_token(account)

    # 自动获取 profile_arn
    profile_arn = await token_manager.fetch_profile_arn(account)

    # 构建 CodeWhisperer 请求
    cw_request = build_codewhisperer_request(anthropic_req, profile_arn)

    # 准备请求头
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token.access_token}",
        "Accept": "application/vnd.amazon.eventstream",
    }

    logger.info(f"Creating streaming request for account: {account.name}")
    logger.debug(f"CodeWhisperer request: {json.dumps(cw_request, ensure_ascii=False)}")

    # 创建 httpx 客户端
    client = httpx.AsyncClient(timeout=120.0)

    try:
        # 使用 stream() 而不是 post()
        response = client.stream(
            "POST",
            config.api.codewhisperer_url,
            json=cw_request,
            headers=headers
        )

        # __aenter__ 来启动连接
        response = await response.__aenter__()

        # 处理认证错误 (401/403)
        if response.status_code in (401, 403) and retry_on_auth_error:
            logger.warning(f"Got {response.status_code}, attempting token refresh...")

            # 关闭当前响应
            await response.aclose()

            # 刷新 token
            token = await token_manager.get_token(account, force_refresh=True)
            headers["Authorization"] = f"Bearer {token.access_token}"

            # 重新创建流式请求
            response = client.stream(
                "POST",
                config.api.codewhisperer_url,
                json=cw_request,
                headers=headers
            )
            response = await response.__aenter__()

        return client, response

    except Exception as e:
        await client.aclose()
        raise


async def handle_streaming_request(
    anthropic_req: AnthropicRequest,
    account: AccountConfig
) -> AsyncGenerator[str, None]:
    """
    处理流式请求（真实流式转发）

    Args:
        anthropic_req: Anthropic 请求
        account: 账号配置

    Yields:
        SSE 格式的字符串
    """
    from .stream_handler import StreamHandler
    from .token_manager import estimate_input_tokens

    # 估算输入 tokens
    input_tokens = estimate_input_tokens(anthropic_req)

    # 创建流式处理器
    handler = StreamHandler(
        model=anthropic_req.model,
        input_tokens=input_tokens
    )

    # 创建流式请求
    try:
        client, response = await proxy_request_streaming(anthropic_req, account)
    except Exception as e:
        logger.error(f"Failed to create streaming request: {e}")
        error_event = {
            "type": "error",
            "error": {
                "type": "api_error",
                "message": f"Failed to create request: {str(e)}"
            }
        }
        yield f"event: error\ndata: {json.dumps(error_event, ensure_ascii=False)}\n\n"
        return

    try:
        if response.status_code != 200:
            error_event = {
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": f"CodeWhisperer returned status {response.status_code}"
                }
            }
            yield f"event: error\ndata: {json.dumps(error_event, ensure_ascii=False)}\n\n"
            return

        # 真实流式转发
        async for sse_event in handler.handle_stream(response.aiter_bytes()):
            yield sse_event

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
    finally:
        # 确保资源被正确释放
        try:
            await response.aclose()
        except:
            pass
        try:
            await client.aclose()
        except:
            pass


# ==================== 通过账号名称处理请求（支持存储系统）====================

async def proxy_request_by_name(
    anthropic_req: AnthropicRequest,
    account_name: str,
    retry_on_auth_error: bool = True
) -> Tuple[int, Dict[str, Any], Optional[bytes]]:
    """
    通过账号名称代理请求到 CodeWhisperer（从存储系统读取 token）

    Args:
        anthropic_req: Anthropic 请求
        account_name: 账号名称
        retry_on_auth_error: 是否在认证错误时重试

    Returns:
        (状态码, 响应头, 响应体)
    """
    config = get_config()
    token_manager = get_token_manager()

    # 获取 token（从存储系统，自动刷新）
    token = await token_manager.get_token_by_name(account_name)

    # 自动获取 profile_arn
    profile_arn = await token_manager.fetch_profile_arn_by_name(account_name)

    # 构建 CodeWhisperer 请求
    cw_request = build_codewhisperer_request(anthropic_req, profile_arn)

    # 准备请求头
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token.access_token}",
        "Accept": "application/vnd.amazon.eventstream",
    }

    logger.info(f"Proxying request for account: {account_name} (from storage)")
    logger.debug(f"CodeWhisperer request: {json.dumps(cw_request, ensure_ascii=False)}")

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                config.api.codewhisperer_url,
                json=cw_request,
                headers=headers
            )

            # 处理认证错误 (401/403)
            if response.status_code in (401, 403) and retry_on_auth_error:
                logger.warning(f"Got {response.status_code}, attempting token refresh...")
                token = await token_manager.get_token_by_name(account_name, force_refresh=True)
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


async def handle_non_streaming_request_by_name(
    anthropic_req: AnthropicRequest,
    account_name: str
) -> Dict[str, Any]:
    """
    通过账号名称处理非流式请求

    Args:
        anthropic_req: Anthropic 请求
        account_name: 账号名称

    Returns:
        Anthropic 格式的响应
    """
    status_code, headers, body = await proxy_request_by_name(anthropic_req, account_name)

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


async def proxy_request_streaming_by_name(
    anthropic_req: AnthropicRequest,
    account_name: str,
    retry_on_auth_error: bool = True
):
    """
    通过账号名称创建流式代理请求（从存储系统读取）

    Args:
        anthropic_req: Anthropic 请求
        account_name: 账号名称
        retry_on_auth_error: 是否在认证错误时重试

    Returns:
        (client, response): httpx client 和响应对象
    """
    config = get_config()
    token_manager = get_token_manager()

    # 获取 token（从存储系统，自动刷新）
    token = await token_manager.get_token_by_name(account_name)

    # 自动获取 profile_arn
    profile_arn = await token_manager.fetch_profile_arn_by_name(account_name)

    # 构建 CodeWhisperer 请求
    cw_request = build_codewhisperer_request(anthropic_req, profile_arn)

    # 准备请求头
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token.access_token}",
        "Accept": "application/vnd.amazon.eventstream",
    }

    logger.info(f"Creating streaming request for account: {account_name} (from storage)")
    logger.debug(f"CodeWhisperer request: {json.dumps(cw_request, ensure_ascii=False)}")

    # 创建 httpx 客户端
    client = httpx.AsyncClient(timeout=120.0)

    try:
        # 使用 stream() 而不是 post()
        response = client.stream(
            "POST",
            config.api.codewhisperer_url,
            json=cw_request,
            headers=headers
        )

        # __aenter__ 来启动连接
        response = await response.__aenter__()

        # 处理认证错误 (401/403)
        if response.status_code in (401, 403) and retry_on_auth_error:
            logger.warning(f"Got {response.status_code}, attempting token refresh...")

            # 关闭当前响应
            await response.aclose()

            # 刷新 token
            token = await token_manager.get_token_by_name(account_name, force_refresh=True)
            headers["Authorization"] = f"Bearer {token.access_token}"

            # 重新创建流式请求
            response = client.stream(
                "POST",
                config.api.codewhisperer_url,
                json=cw_request,
                headers=headers
            )
            response = await response.__aenter__()

        return client, response

    except Exception as e:
        await client.aclose()
        raise


async def handle_streaming_request_by_name(
    anthropic_req: AnthropicRequest,
    account_name: str
) -> AsyncGenerator[str, None]:
    """
    通过账号名称处理流式请求（真实流式转发）

    Args:
        anthropic_req: Anthropic 请求
        account_name: 账号名称

    Yields:
        SSE 格式的字符串
    """
    from .stream_handler import StreamHandler
    from .token_manager import estimate_input_tokens

    # 估算输入 tokens
    input_tokens = estimate_input_tokens(anthropic_req)

    # 创建流式处理器
    handler = StreamHandler(
        model=anthropic_req.model,
        input_tokens=input_tokens
    )

    # 创建流式请求
    try:
        client, response = await proxy_request_streaming_by_name(anthropic_req, account_name)
    except Exception as e:
        logger.error(f"Failed to create streaming request: {e}")
        error_event = {
            "type": "error",
            "error": {
                "type": "api_error",
                "message": f"Failed to create request: {str(e)}"
            }
        }
        yield f"event: error\ndata: {json.dumps(error_event, ensure_ascii=False)}\n\n"
        return

    try:
        if response.status_code != 200:
            error_event = {
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": f"CodeWhisperer returned status {response.status_code}"
                }
            }
            yield f"event: error\ndata: {json.dumps(error_event, ensure_ascii=False)}\n\n"
            return

        # 真实流式转发
        async for sse_event in handler.handle_stream(response.aiter_bytes()):
            yield sse_event

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
    finally:
        # 确保资源被正确释放
        try:
            await response.aclose()
        except:
            pass
        try:
            await client.aclose()
        except:
            pass
