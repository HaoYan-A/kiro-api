"""
请求转换模块
将 Anthropic API 请求转换为 CodeWhisperer 格式
"""
import uuid
from typing import Any, Dict, List, Optional, Union

from .config import AccountConfig, get_config
from .models import AnthropicRequest


def generate_uuid() -> str:
    """生成 UUID v4"""
    return str(uuid.uuid4())


def get_message_content(content: Union[str, List[Dict[str, Any]]]) -> str:
    """
    从消息中提取文本内容

    Args:
        content: 消息内容，可以是字符串或内容块列表

    Returns:
        提取的文本内容
    """
    if isinstance(content, str):
        return content if content else "answer for user question"

    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict):
                block_type = block.get("type", "")
                if block_type == "text":
                    text = block.get("text", "")
                    if text:
                        texts.append(text)
                elif block_type == "tool_result":
                    # 处理 tool_result 类型
                    tool_content = block.get("content", "")
                    if isinstance(tool_content, str):
                        texts.append(tool_content)
                    elif isinstance(tool_content, list):
                        for item in tool_content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                texts.append(item.get("text", ""))
        return "\n".join(texts) if texts else "answer for user question"

    return "answer for user question"


def convert_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    转换 Anthropic 工具格式到 CodeWhisperer 格式

    Args:
        tools: Anthropic 格式的工具列表

    Returns:
        CodeWhisperer 格式的工具列表
    """
    cw_tools = []
    for tool in tools:
        cw_tool = {
            "toolSpecification": {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "inputSchema": {
                    "json": tool.get("input_schema", {})
                }
            }
        }
        cw_tools.append(cw_tool)
    return cw_tools


def build_codewhisperer_request(
    anthropic_req: AnthropicRequest,
    account: AccountConfig
) -> Dict[str, Any]:
    """
    构建 CodeWhisperer 请求

    Args:
        anthropic_req: Anthropic API 请求
        account: 账号配置

    Returns:
        CodeWhisperer 请求字典
    """
    config = get_config()
    mapped_model = config.map_model(anthropic_req.model)

    # 获取最后一条消息的内容
    last_message = anthropic_req.messages[-1]
    last_content = last_message.content
    if isinstance(last_content, list):
        # 转换为字典列表
        last_content = [
            item.model_dump() if hasattr(item, 'model_dump') else item
            for item in last_content
        ]
    current_message_content = get_message_content(last_content)

    # 构建基本请求结构
    cw_request = {
        "profileArn": account.profile_arn,
        "conversationState": {
            "chatTriggerType": "MANUAL",
            "conversationId": generate_uuid(),
            "currentMessage": {
                "userInputMessage": {
                    "content": current_message_content,
                    "modelId": mapped_model,
                    "origin": "AI_EDITOR",
                    "userInputMessageContext": {}
                }
            },
            "history": []
        }
    }

    # 处理 tools
    if anthropic_req.tools:
        cw_request["conversationState"]["currentMessage"]["userInputMessage"]["userInputMessageContext"]["tools"] = convert_tools(anthropic_req.tools)

    # 构建历史消息
    history = []

    # 处理 system 消息
    if anthropic_req.system:
        system_messages = anthropic_req.system
        if isinstance(system_messages, str):
            # system 是字符串
            system_text = system_messages
            user_msg = {
                "userInputMessage": {
                    "content": system_text,
                    "modelId": mapped_model,
                    "origin": "AI_EDITOR"
                }
            }
            assistant_msg = {
                "assistantResponseMessage": {
                    "content": "I will follow these instructions",
                    "toolUses": []
                }
            }
            history.append(user_msg)
            history.append(assistant_msg)
        elif isinstance(system_messages, list):
            # system 是消息列表
            for sys_msg in system_messages:
                if isinstance(sys_msg, dict):
                    sys_text = sys_msg.get("text", "")
                else:
                    sys_text = str(sys_msg)

                user_msg = {
                    "userInputMessage": {
                        "content": sys_text,
                        "modelId": mapped_model,
                        "origin": "AI_EDITOR"
                    }
                }
                assistant_msg = {
                    "assistantResponseMessage": {
                        "content": "I will follow these instructions",
                        "toolUses": []
                    }
                }
                history.append(user_msg)
                history.append(assistant_msg)

    # 处理常规消息历史（不包括最后一条）
    messages = anthropic_req.messages
    i = 0
    while i < len(messages) - 1:
        msg = messages[i]
        msg_content = msg.content
        if isinstance(msg_content, list):
            msg_content = [
                item.model_dump() if hasattr(item, 'model_dump') else item
                for item in msg_content
            ]

        if msg.role == "user":
            user_msg = {
                "userInputMessage": {
                    "content": get_message_content(msg_content),
                    "modelId": mapped_model,
                    "origin": "AI_EDITOR"
                }
            }
            history.append(user_msg)

            # 检查下一条消息是否是助手回复
            if i + 1 < len(messages) - 1 and messages[i + 1].role == "assistant":
                next_content = messages[i + 1].content
                if isinstance(next_content, list):
                    next_content = [
                        item.model_dump() if hasattr(item, 'model_dump') else item
                        for item in next_content
                    ]
                assistant_msg = {
                    "assistantResponseMessage": {
                        "content": get_message_content(next_content),
                        "toolUses": []
                    }
                }
                history.append(assistant_msg)
                i += 1  # 跳过已处理的助手消息
        i += 1

    cw_request["conversationState"]["history"] = history

    return cw_request
