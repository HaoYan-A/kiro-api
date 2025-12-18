"""
AWS Event Stream 解析器
解析 AWS CodeWhisperer 返回的 vnd.amazon.eventstream 格式数据
"""
import struct
import json
import logging
from typing import Optional, Dict, Any, AsyncIterator

logger = logging.getLogger(__name__)


class EventStreamParser:
    """
    AWS Event Stream 解析器

    Event Stream 格式：
    - Prelude (12 bytes):
      - Total length (4 bytes, big-endian uint32)
      - Headers length (4 bytes, big-endian uint32)
      - Prelude CRC (4 bytes, big-endian uint32)
    - Headers (variable length)
    - Payload (variable length)
    - Message CRC (4 bytes, big-endian uint32)
    """

    @staticmethod
    def parse_headers(headers_data: bytes) -> Dict[str, str]:
        """
        解析事件头部

        头部格式：
        - Header name length (1 byte)
        - Header name (variable)
        - Header value type (1 byte, 7=string)
        - Header value length (2 bytes, big-endian uint16)
        - Header value (variable)
        """
        headers = {}
        offset = 0

        while offset < len(headers_data):
            # 读取头部名称长度
            if offset >= len(headers_data):
                break
            name_length = headers_data[offset]
            offset += 1

            # 读取头部名称
            if offset + name_length > len(headers_data):
                break
            name = headers_data[offset:offset + name_length].decode('utf-8')
            offset += name_length

            # 读取值类型
            if offset >= len(headers_data):
                break
            value_type = headers_data[offset]
            offset += 1

            # 读取值长度（2 字节）
            if offset + 2 > len(headers_data):
                break
            value_length = struct.unpack('>H', headers_data[offset:offset + 2])[0]
            offset += 2

            # 读取值
            if offset + value_length > len(headers_data):
                break

            if value_type == 7:  # String type
                value = headers_data[offset:offset + value_length].decode('utf-8')
            else:
                value = headers_data[offset:offset + value_length]

            offset += value_length
            headers[name] = value

        return headers

    @staticmethod
    def parse_message(data: bytes) -> Optional[Dict[str, Any]]:
        """
        解析单个 Event Stream 消息

        Args:
            data: 完整的消息字节数据

        Returns:
            Optional[Dict[str, Any]]: 解析后的消息，包含 headers 和 payload
        """
        try:
            if len(data) < 16:  # 最小消息长度
                return None

            # 解析 Prelude (12 bytes)
            total_length = struct.unpack('>I', data[0:4])[0]
            headers_length = struct.unpack('>I', data[4:8])[0]
            # prelude_crc = struct.unpack('>I', data[8:12])[0]

            # 验证长度
            if len(data) < total_length:
                logger.warning(f"消息不完整: 期望 {total_length} 字节，实际 {len(data)} 字节")
                return None

            # 解析头部
            headers_data = data[12:12 + headers_length]
            headers = EventStreamParser.parse_headers(headers_data)

            # 解析 Payload
            payload_start = 12 + headers_length
            payload_end = total_length - 4  # 减去最后的 CRC
            payload_data = data[payload_start:payload_end]

            # 尝试解析 JSON payload
            payload = None
            if payload_data:
                try:
                    payload = json.loads(payload_data.decode('utf-8'))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    payload = payload_data

            return {
                'headers': headers,
                'payload': payload,
                'total_length': total_length
            }

        except Exception as e:
            logger.error(f"解析消息失败: {e}", exc_info=True)
            return None

    @staticmethod
    async def parse_stream(byte_stream: AsyncIterator[bytes]) -> AsyncIterator[Dict[str, Any]]:
        """
        解析字节流，提取事件

        Args:
            byte_stream: 异步字节流

        Yields:
            Dict[str, Any]: 解析后的事件
        """
        buffer = bytearray()

        async for chunk in byte_stream:
            buffer.extend(chunk)

            # 尝试解析缓冲区中的消息
            while len(buffer) >= 12:
                # 读取消息总长度
                try:
                    total_length = struct.unpack('>I', buffer[0:4])[0]
                except struct.error:
                    break

                # 检查是否有完整的消息
                if len(buffer) < total_length:
                    break

                # 提取完整消息
                message_data = bytes(buffer[:total_length])
                buffer = buffer[total_length:]

                # 解析消息
                message = EventStreamParser.parse_message(message_data)
                if message:
                    yield message


def extract_event_info(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    从解析后的消息中提取事件信息

    Args:
        message: 解析后的消息

    Returns:
        Optional[Dict[str, Any]]: 事件信息
    """
    headers = message.get('headers', {})
    payload = message.get('payload')

    event_type = headers.get(':event-type') or headers.get('event-type')
    content_type = headers.get(':content-type') or headers.get('content-type')
    message_type = headers.get(':message-type') or headers.get('message-type')

    return {
        'event_type': event_type,
        'content_type': content_type,
        'message_type': message_type,
        'payload': payload
    }
