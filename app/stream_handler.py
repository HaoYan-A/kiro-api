"""
流式处理模块
处理 AWS CodeWhisperer Event Stream 响应并转换为 Claude 格式
"""
import json
import logging
from datetime import datetime
from typing import AsyncIterator, Optional

from .event_stream_parser import EventStreamParser, extract_event_info

logger = logging.getLogger(__name__)

THINKING_START_TAG = "<thinking>"
THINKING_END_TAG = "</thinking>"


def _pending_tag_suffix(buffer: str, tag: str) -> int:
    """检测 buffer 末尾是否是 tag 的部分前缀"""
    if not buffer or not tag:
        return 0
    max_len = min(len(buffer), len(tag) - 1)
    for length in range(max_len, 0, -1):
        if buffer[-length:] == tag[:length]:
            return length
    return 0


def generate_message_id() -> str:
    """生成消息 ID"""
    return f"msg_{datetime.now().strftime('%Y%m%d%H%M%S')}"


def build_sse_event(event_name: str, data: dict) -> str:
    """构建 SSE 事件字符串"""
    data_str = json.dumps(data, ensure_ascii=False)
    return f"event: {event_name}\ndata: {data_str}\n\n"


class StreamHandler:
    """流式事件处理器"""

    def __init__(self, model: str, input_tokens: int):
        # 响应文本累积缓冲区
        self.response_buffer: list[str] = []

        # 内容块索引
        self.content_block_index: int = -1

        # 内容块是否已开始
        self.content_block_started: bool = False

        # 内容块开始是否已发送
        self.content_block_start_sent: bool = False

        # 内容块停止是否已发送
        self.content_block_stop_sent: bool = False

        # 对话 ID
        self.conversation_id: Optional[str] = None

        # 原始请求的 model
        self.model: str = model

        # 输入 token 数量
        self.input_tokens: int = input_tokens

        # 是否已发送 message_start
        self.message_start_sent: bool = False

        # 消息 ID
        self.message_id: str = generate_message_id()

        # Tool use 相关状态
        self.current_tool_use: Optional[dict] = None
        self.tool_input_buffer: list[str] = []
        self.tool_use_id: Optional[str] = None
        self.tool_name: Optional[str] = None

        # 已处理的 tool_use_id 集合（用于去重）
        self._processed_tool_use_ids: set = set()

        # 所有 tool use 的完整 input(用于 token 统计)
        self.all_tool_inputs: list[str] = []

        # Thinking 标签状态
        self.in_think_block: bool = False
        self.think_buffer: str = ""
        self.pending_start_tag_chars: int = 0

    async def handle_stream(
        self,
        upstream_bytes: AsyncIterator[bytes]
    ) -> AsyncIterator[str]:
        """
        处理上游 Event Stream 并转换为 Claude 格式

        Args:
            upstream_bytes: 上游字节流

        Yields:
            str: Claude 格式的 SSE 事件
        """
        try:
            # 使用 Event Stream 解析器
            parser = EventStreamParser()

            async for message in parser.parse_stream(upstream_bytes):
                # 提取事件信息
                event_info = extract_event_info(message)
                if not event_info:
                    continue

                event_type = event_info.get('event_type')
                payload = event_info.get('payload', {})

                logger.debug(f"收到事件: {event_type}")

                # 处理 initial-response 事件
                if event_type == 'initial-response':
                    self.conversation_id = payload.get('conversationId', self.message_id)

                    # 发送 message_start
                    if not self.message_start_sent:
                        message_start = {
                            "type": "message_start",
                            "message": {
                                "id": self.message_id,
                                "type": "message",
                                "role": "assistant",
                                "content": [],
                                "model": self.model,
                                "stop_reason": None,
                                "stop_sequence": None,
                                "usage": {
                                    "input_tokens": self.input_tokens,
                                    "output_tokens": 1
                                }
                            }
                        }
                        yield build_sse_event("message_start", message_start)
                        self.message_start_sent = True

                        # 发送 ping
                        yield build_sse_event("ping", {"type": "ping"})

                # 处理 assistantResponseEvent 事件
                elif event_type == 'assistantResponseEvent':
                    # 如果之前有 tool use 块未关闭,先关闭它
                    if self.current_tool_use and not self.content_block_stop_sent:
                        yield self._build_content_block_stop()
                        self.content_block_stop_sent = True
                        self.current_tool_use = None

                    # 处理文本内容
                    content = payload.get('content', '')
                    if content:
                        self.think_buffer += content

                        while self.think_buffer:
                            # 处理待处理的开始标签字符
                            if self.pending_start_tag_chars > 0:
                                if len(self.think_buffer) < self.pending_start_tag_chars:
                                    self.pending_start_tag_chars -= len(self.think_buffer)
                                    self.think_buffer = ""
                                    break
                                else:
                                    self.think_buffer = self.think_buffer[self.pending_start_tag_chars:]
                                    self.pending_start_tag_chars = 0
                                    if not self.think_buffer:
                                        break
                                    continue

                            if not self.in_think_block:
                                # 查找 <thinking> 标签
                                think_start = self.think_buffer.find(THINKING_START_TAG)
                                if think_start == -1:
                                    # 检查是否有部分标签在末尾
                                    pending = _pending_tag_suffix(self.think_buffer, THINKING_START_TAG)
                                    if pending == len(self.think_buffer) and pending > 0:
                                        # 整个 buffer 都是标签前缀，关闭文本块，开启 thinking 块
                                        if self.content_block_start_sent:
                                            yield self._build_content_block_stop()
                                            self.content_block_stop_sent = True
                                            self.content_block_start_sent = False

                                        self.content_block_index += 1
                                        yield self._build_content_block_start("thinking")
                                        self.content_block_start_sent = True
                                        self.content_block_started = True
                                        self.content_block_stop_sent = False
                                        self.in_think_block = True
                                        self.pending_start_tag_chars = len(THINKING_START_TAG) - pending
                                        self.think_buffer = ""
                                        break

                                    # 发送非标签部分
                                    emit_len = len(self.think_buffer) - pending
                                    if emit_len <= 0:
                                        break
                                    text_chunk = self.think_buffer[:emit_len]
                                    if text_chunk:
                                        if not self.content_block_start_sent:
                                            self.content_block_index += 1
                                            yield self._build_content_block_start("text")
                                            self.content_block_start_sent = True
                                            self.content_block_started = True
                                            self.content_block_stop_sent = False
                                        self.response_buffer.append(text_chunk)
                                        yield self._build_content_block_delta(text_chunk, "text")
                                    self.think_buffer = self.think_buffer[emit_len:]
                                else:
                                    # 找到完整的 <thinking> 标签
                                    before_text = self.think_buffer[:think_start]
                                    if before_text:
                                        if not self.content_block_start_sent:
                                            self.content_block_index += 1
                                            yield self._build_content_block_start("text")
                                            self.content_block_start_sent = True
                                            self.content_block_started = True
                                            self.content_block_stop_sent = False
                                        self.response_buffer.append(before_text)
                                        yield self._build_content_block_delta(before_text, "text")
                                    self.think_buffer = self.think_buffer[think_start + len(THINKING_START_TAG):]

                                    # 关闭文本块，开启 thinking 块
                                    if self.content_block_start_sent:
                                        yield self._build_content_block_stop()
                                        self.content_block_stop_sent = True
                                        self.content_block_start_sent = False

                                    self.content_block_index += 1
                                    yield self._build_content_block_start("thinking")
                                    self.content_block_start_sent = True
                                    self.content_block_started = True
                                    self.content_block_stop_sent = False
                                    self.in_think_block = True
                                    self.pending_start_tag_chars = 0
                            else:
                                # 在 thinking 块中，查找 </thinking> 标签
                                think_end = self.think_buffer.find(THINKING_END_TAG)
                                if think_end == -1:
                                    # 检查是否有部分结束标签
                                    pending = _pending_tag_suffix(self.think_buffer, THINKING_END_TAG)
                                    emit_len = len(self.think_buffer) - pending
                                    if emit_len <= 0:
                                        break
                                    thinking_chunk = self.think_buffer[:emit_len]
                                    if thinking_chunk:
                                        yield self._build_content_block_delta(thinking_chunk, "thinking")
                                    self.think_buffer = self.think_buffer[emit_len:]
                                else:
                                    # 找到完整的 </thinking> 标签
                                    thinking_chunk = self.think_buffer[:think_end]
                                    if thinking_chunk:
                                        yield self._build_content_block_delta(thinking_chunk, "thinking")
                                    self.think_buffer = self.think_buffer[think_end + len(THINKING_END_TAG):]

                                    # 关闭 thinking 块
                                    yield self._build_content_block_stop()
                                    self.content_block_stop_sent = True
                                    self.content_block_start_sent = False
                                    self.in_think_block = False

                # 处理 toolUseEvent 事件
                elif event_type == 'toolUseEvent':
                    async for tool_event in self._handle_tool_use_event(payload):
                        yield tool_event

            # 流结束，发送收尾事件
            if self.content_block_started and not self.content_block_stop_sent:
                yield self._build_content_block_stop()
                self.content_block_stop_sent = True

            # 计算 output token 数量
            full_text_response = "".join(self.response_buffer)
            full_tool_inputs = "".join(self.all_tool_inputs)
            output_tokens = self._count_tokens(full_text_response + full_tool_inputs)

            logger.info(f"Token 统计 - 输入: {self.input_tokens}, 输出: {output_tokens}")

            # 发送 message_delta
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
            yield build_sse_event("message_delta", message_delta)

            # 发送 message_stop
            yield build_sse_event("message_stop", {"type": "message_stop"})

        except Exception as e:
            logger.error(f"处理流时发生错误: {e}", exc_info=True)
            raise

    async def _handle_tool_use_event(self, payload: dict) -> AsyncIterator[str]:
        """处理 tool use 事件"""
        try:
            tool_use_id = payload.get('toolUseId')
            tool_name = payload.get('name')
            tool_input = payload.get('input', {})
            is_stop = payload.get('stop', False)

            # 如果是新 tool use 事件的开始
            if tool_use_id and tool_name and not self.current_tool_use:
                logger.info(f"开始新的 tool use: {tool_name} (ID: {tool_use_id})")

                # 如果之前有文本块未关闭,先关闭它
                if self.content_block_start_sent and not self.content_block_stop_sent:
                    yield self._build_content_block_stop()
                    self.content_block_stop_sent = True

                # 记录这个 tool_use_id 为已处理
                self._processed_tool_use_ids.add(tool_use_id)

                # 内容块索引递增
                self.content_block_index += 1

                # 发送 content_block_start (tool_use type)
                content_block_start = {
                    "type": "content_block_start",
                    "index": self.content_block_index,
                    "content_block": {
                        "type": "tool_use",
                        "id": tool_use_id,
                        "name": tool_name,
                        "input": {}
                    }
                }
                yield build_sse_event("content_block_start", content_block_start)

                self.content_block_started = True
                self.current_tool_use = {
                    'toolUseId': tool_use_id,
                    'name': tool_name
                }
                self.tool_use_id = tool_use_id
                self.tool_name = tool_name
                self.tool_input_buffer = []

            # 如果是正在处理的 tool use，累积 input 片段
            if self.current_tool_use and tool_input:
                if isinstance(tool_input, str):
                    input_fragment = tool_input
                elif isinstance(tool_input, dict):
                    input_fragment = json.dumps(tool_input, ensure_ascii=False)
                else:
                    input_fragment = str(tool_input)

                self.tool_input_buffer.append(input_fragment)

                # 发送 input_json_delta
                content_block_delta = {
                    "type": "content_block_delta",
                    "index": self.content_block_index,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": input_fragment
                    }
                }
                yield build_sse_event("content_block_delta", content_block_delta)

            # 如果是 stop 事件，发送 content_block_stop
            if is_stop and self.current_tool_use:
                full_input = "".join(self.tool_input_buffer)
                logger.info(f"完成 tool use: {self.tool_name} ({len(full_input)} 字符)")

                # 保存完整的 tool input 用于 token 统计
                self.all_tool_inputs.append(full_input)

                yield self._build_content_block_stop()

                # 重置状态
                self.content_block_stop_sent = False
                self.content_block_started = False
                self.content_block_start_sent = False
                self.current_tool_use = None
                self.tool_use_id = None
                self.tool_name = None
                self.tool_input_buffer = []

        except Exception as e:
            logger.error(f"处理 tool use 事件失败: {e}", exc_info=True)
            raise

    def _build_content_block_start(self, block_type: str) -> str:
        """构建 content_block_start 事件"""
        if block_type == "text":
            content_block = {"type": "text", "text": ""}
        elif block_type == "thinking":
            content_block = {"type": "thinking", "thinking": ""}
        else:
            content_block = {"type": block_type}

        data = {
            "type": "content_block_start",
            "index": self.content_block_index,
            "content_block": content_block
        }
        return build_sse_event("content_block_start", data)

    def _build_content_block_delta(self, text: str, block_type: str) -> str:
        """构建 content_block_delta 事件"""
        if block_type == "thinking":
            delta = {"type": "thinking_delta", "thinking": text}
        else:
            delta = {"type": "text_delta", "text": text}

        data = {
            "type": "content_block_delta",
            "index": self.content_block_index,
            "delta": delta
        }
        return build_sse_event("content_block_delta", data)

    def _build_content_block_stop(self) -> str:
        """构建 content_block_stop 事件"""
        data = {
            "type": "content_block_stop",
            "index": self.content_block_index
        }
        return build_sse_event("content_block_stop", data)

    def _count_tokens(self, text: str) -> int:
        """
        使用 tiktoken 精确计算 token 数量

        Args:
            text: 文本内容

        Returns:
            int: token 数量
        """
        if not text:
            return 0

        try:
            import tiktoken
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except ImportError:
            logger.warning("tiktoken 未安装，使用简化估算")
            return max(1, len(text) // 4)
        except Exception as e:
            logger.debug(f"tiktoken 计数失败，使用简化估算: {e}")
            return max(1, len(text) // 4)
