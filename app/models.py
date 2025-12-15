"""
数据模型定义
包含 Anthropic API 和 CodeWhisperer API 的请求/响应模型
"""
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


# ============== Anthropic API 模型 ==============

class AnthropicContentBlock(BaseModel):
    """Anthropic 消息内容块"""
    type: str
    text: Optional[str] = None
    source: Optional[Dict[str, Any]] = None  # for image type
    # tool_use fields
    id: Optional[str] = None
    name: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    # tool_result fields
    tool_use_id: Optional[str] = None
    content: Optional[Union[str, List[Dict[str, Any]]]] = None


class AnthropicMessage(BaseModel):
    """Anthropic 消息"""
    role: str
    content: Union[str, List[AnthropicContentBlock], List[Dict[str, Any]]]


class AnthropicRequest(BaseModel):
    """Anthropic API 请求"""
    model: str
    messages: List[AnthropicMessage]
    max_tokens: int = 4096
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    stream: bool = False
    system: Optional[Union[str, List[Dict[str, Any]]]] = None
    stop_sequences: Optional[List[str]] = None
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


class AnthropicUsage(BaseModel):
    """Anthropic 使用统计"""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


class AnthropicResponseContent(BaseModel):
    """Anthropic 响应内容"""
    type: str
    text: Optional[str] = None
    id: Optional[str] = None
    name: Optional[str] = None
    input: Optional[Dict[str, Any]] = None


class AnthropicResponse(BaseModel):
    """Anthropic API 响应"""
    id: str
    type: str = "message"
    role: str = "assistant"
    content: List[AnthropicResponseContent] = Field(default_factory=list)
    model: str
    stop_reason: Optional[str] = None
    stop_sequence: Optional[str] = None
    usage: AnthropicUsage = Field(default_factory=AnthropicUsage)


# ============== CodeWhisperer API 模型 ==============

class ConversationState(BaseModel):
    """会话状态"""
    conversationId: Optional[str] = None
    currentMessage: Optional[Dict[str, Any]] = None
    history: List[Dict[str, Any]] = Field(default_factory=list)
    systemPrompt: Optional[str] = None


class CodeWhispererRequest(BaseModel):
    """CodeWhisperer API 请求"""
    profileArn: str
    conversationState: ConversationState
    source: str = "CHAT"


# ============== SSE 事件模型 ==============

class SSEEvent(BaseModel):
    """SSE 事件"""
    event: str
    data: Dict[str, Any]


class MessageStartEvent(BaseModel):
    """message_start 事件数据"""
    type: str = "message_start"
    message: Dict[str, Any]


class ContentBlockStartEvent(BaseModel):
    """content_block_start 事件数据"""
    type: str = "content_block_start"
    index: int
    content_block: Dict[str, Any]


class ContentBlockDeltaEvent(BaseModel):
    """content_block_delta 事件数据"""
    type: str = "content_block_delta"
    index: int
    delta: Dict[str, Any]


class ContentBlockStopEvent(BaseModel):
    """content_block_stop 事件数据"""
    type: str = "content_block_stop"
    index: int


class MessageDeltaEvent(BaseModel):
    """message_delta 事件数据"""
    type: str = "message_delta"
    delta: Dict[str, Any]
    usage: Optional[Dict[str, int]] = None


class MessageStopEvent(BaseModel):
    """message_stop 事件数据"""
    type: str = "message_stop"
