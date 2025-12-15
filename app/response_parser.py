"""
响应解析模块
解析 AWS CodeWhisperer 的二进制 Event Stream 响应
"""
import json
import logging
import struct
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)


class AssistantResponseEvent:
    """助手响应事件"""

    def __init__(self, data: Dict[str, Any]):
        self.content: str = data.get("content", "")
        self.input: Optional[str] = data.get("input")
        self.name: str = data.get("name", "")
        self.tool_use_id: str = data.get("toolUseId", "")
        self.stop: bool = data.get("stop", False)


class SSEEvent:
    """Server-Sent Event"""

    def __init__(self, event: str, data: Dict[str, Any]):
        self.event = event
        self.data = data

    def to_dict(self) -> Dict[str, Any]:
        return {"event": self.event, "data": self.data}

    def to_sse_string(self) -> str:
        """转换为 SSE 格式字符串"""
        if not self.event or self.data is None:
            return ""
        data_str = json.dumps(self.data, ensure_ascii=False)
        return f"event: {self.event}\ndata: {data_str}\n\n"


def parse_binary_events(data: bytes) -> List[SSEEvent]:
    """
    解析 AWS Event Stream 二进制响应

    Args:
        data: 二进制响应数据

    Returns:
        SSE 事件列表
    """
    events = []
    offset = 0

    while offset + 12 <= len(data):
        # 读取总长度和头部长度（大端序）
        try:
            total_len, header_len = struct.unpack_from(">II", data, offset)
        except struct.error:
            break

        # 验证长度
        if offset + total_len > len(data):
            logger.warning(f"Frame length invalid: total_len={total_len}, remaining={len(data) - offset}")
            break

        # 跳过 prelude CRC (4 bytes)
        header_start = offset + 12

        # 跳过 headers
        payload_start = header_start + header_len

        # 计算 payload 长度 (总长度 - 头部长度 - 12字节prelude - 4字节CRC)
        payload_len = total_len - header_len - 16
        if payload_len < 0:
            break

        payload_end = payload_start + payload_len
        payload = data[payload_start:payload_end]

        # 解析 payload
        try:
            payload_str = payload.decode("utf-8")
            # 去除可能的 "vent" 前缀
            if payload_str.startswith("vent"):
                payload_str = payload_str[4:]

            evt_data = json.loads(payload_str)
            evt = AssistantResponseEvent(evt_data)

            sse_event = convert_assistant_event_to_sse(evt)
            if sse_event.event:
                events.append(sse_event)

            # 处理 tool_use 结束
            if evt.tool_use_id and evt.name and evt.stop:
                events.append(SSEEvent(
                    event="message_delta",
                    data={
                        "type": "message_delta",
                        "delta": {
                            "stop_reason": "tool_use",
                            "stop_sequence": None
                        },
                        "usage": {"output_tokens": 0}
                    }
                ))

        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.debug(f"Failed to parse payload: {e}")

        # 移动到下一帧
        offset += total_len

    return events


def parse_binary_events_streaming(data: bytes) -> Generator[SSEEvent, None, None]:
    """
    流式解析 AWS Event Stream 二进制响应

    Args:
        data: 二进制响应数据

    Yields:
        SSE 事件
    """
    events = parse_binary_events(data)
    for event in events:
        yield event


def convert_assistant_event_to_sse(evt: AssistantResponseEvent) -> SSEEvent:
    """
    将助手响应事件转换为 SSE 事件

    Args:
        evt: 助手响应事件

    Returns:
        SSE 事件
    """
    if evt.content:
        # 文本内容
        return SSEEvent(
            event="content_block_delta",
            data={
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "text_delta",
                    "text": evt.content
                }
            }
        )
    elif evt.tool_use_id and evt.name and not evt.stop:
        # 工具调用
        if evt.input is None:
            # 工具调用开始
            return SSEEvent(
                event="content_block_start",
                data={
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": evt.tool_use_id,
                        "name": evt.name,
                        "input": {}
                    }
                }
            )
        else:
            # 工具输入增量
            return SSEEvent(
                event="content_block_delta",
                data={
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {
                        "type": "input_json_delta",
                        "id": evt.tool_use_id,
                        "name": evt.name,
                        "partial_json": evt.input
                    }
                }
            )
    elif evt.stop:
        # 内容块结束
        return SSEEvent(
            event="content_block_stop",
            data={
                "type": "content_block_stop",
                "index": 1
            }
        )

    # 返回空事件
    return SSEEvent(event="", data={})


def collect_full_response(events: List[SSEEvent]) -> Dict[str, Any]:
    """
    从 SSE 事件列表中收集完整响应

    Args:
        events: SSE 事件列表

    Returns:
        完整的 Anthropic 响应
    """
    content_blocks = []
    current_text = ""
    tool_uses = {}
    stop_reason = "end_turn"
    output_tokens = 0

    for evt in events:
        if evt.event == "content_block_delta":
            delta = evt.data.get("delta", {})
            delta_type = delta.get("type", "")

            if delta_type == "text_delta":
                current_text += delta.get("text", "")
            elif delta_type == "input_json_delta":
                tool_id = delta.get("id", "")
                if tool_id not in tool_uses:
                    tool_uses[tool_id] = {
                        "id": tool_id,
                        "name": delta.get("name", ""),
                        "input_json": ""
                    }
                tool_uses[tool_id]["input_json"] += delta.get("partial_json", "")

        elif evt.event == "content_block_start":
            content_block = evt.data.get("content_block", {})
            if content_block.get("type") == "tool_use":
                tool_id = content_block.get("id", "")
                tool_uses[tool_id] = {
                    "id": tool_id,
                    "name": content_block.get("name", ""),
                    "input_json": ""
                }

        elif evt.event == "message_delta":
            delta = evt.data.get("delta", {})
            if "stop_reason" in delta:
                stop_reason = delta["stop_reason"]
            usage = evt.data.get("usage", {})
            if "output_tokens" in usage:
                output_tokens = usage["output_tokens"]

    # 构建内容块
    if current_text:
        content_blocks.append({
            "type": "text",
            "text": current_text
        })

    for tool_data in tool_uses.values():
        try:
            input_data = json.loads(tool_data["input_json"]) if tool_data["input_json"] else {}
        except json.JSONDecodeError:
            input_data = {}

        content_blocks.append({
            "type": "tool_use",
            "id": tool_data["id"],
            "name": tool_data["name"],
            "input": input_data
        })

    return {
        "content": content_blocks,
        "stop_reason": stop_reason,
        "output_tokens": output_tokens
    }
