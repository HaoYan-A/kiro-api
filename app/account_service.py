"""
账号服务模块
提供账号管理和 Token 操作的业务逻辑
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import httpx

from .storage import get_storage

logger = logging.getLogger(__name__)


def generate_api_key(name: str) -> str:
    """生成 API Key"""
    random_part = secrets.token_hex(16)
    return f"sk-kiro-{name}-{random_part}"


class AccountService:
    """账号服务"""

    # AWS OIDC Token 刷新 URL
    REFRESH_URL = "https://oidc.us-east-1.amazonaws.com/token"
    # ListAvailableProfiles API URL
    LIST_PROFILES_URL = "https://q.us-east-1.amazonaws.com/ListAvailableProfiles"
    # Test API URL
    TEST_API_URL = "https://q.us-east-1.amazonaws.com/generateAssistantResponse"

    def __init__(self):
        self.storage = get_storage()

    def list_accounts(self) -> List[dict]:
        """列出所有账号，包含 token 状态"""
        accounts = self.storage.list_accounts()
        result = []
        for account in accounts:
            account_info = account.copy()
            # 获取 token 状态
            token = self.storage.get_token(account["name"])
            if token:
                account_info["has_token"] = True
                account_info["expires_at"] = token.get("expires_at")
                account_info["is_expired"] = self._is_token_expired(token)
            else:
                account_info["has_token"] = False
                account_info["expires_at"] = None
                account_info["is_expired"] = True
            result.append(account_info)
        return result

    def get_account(self, name: str) -> Optional[dict]:
        """获取账号详情"""
        account = self.storage.get_account(name)
        if not account:
            return None

        account_info = account.copy()
        token = self.storage.get_token(name)
        if token:
            account_info["has_token"] = True
            account_info["expires_at"] = token.get("expires_at")
            account_info["is_expired"] = self._is_token_expired(token)
            account_info["token"] = {
                "access_token": token.get("access_token", "")[:50] + "..." if token.get("access_token") else None,
                "refresh_token": token.get("refresh_token", "")[:50] + "..." if token.get("refresh_token") else None,
                "expires_at": token.get("expires_at"),
                "client_id_hash": token.get("client_id_hash"),
                "has_client_credentials": bool(token.get("client_id") and token.get("client_secret")),
            }
        else:
            account_info["has_token"] = False
            account_info["expires_at"] = None
            account_info["is_expired"] = True
        return account_info

    def get_account_by_api_key(self, api_key: str) -> Optional[dict]:
        """通过 API Key 获取账号"""
        return self.storage.get_account_by_api_key(api_key)

    def create_account(self, name: str, api_key: Optional[str] = None) -> dict:
        """创建账号"""
        if not api_key:
            api_key = generate_api_key(name)

        account = {
            "name": name,
            "api_key": api_key,
            "enabled": True,
        }
        return self.storage.create_account(account)

    def update_account(self, name: str, updates: dict) -> Optional[dict]:
        """更新账号"""
        return self.storage.update_account(name, updates)

    def delete_account(self, name: str) -> bool:
        """删除账号"""
        return self.storage.delete_account(name)

    def toggle_account(self, name: str) -> Optional[dict]:
        """切换账号启用状态"""
        return self.storage.toggle_account(name)

    def save_token(self, account_name: str, token_data: dict) -> None:
        """保存 Token 数据"""
        self.storage.save_token(account_name, token_data)

    def get_token(self, account_name: str) -> Optional[dict]:
        """获取 Token 数据"""
        return self.storage.get_token(account_name)

    def _is_token_expired(self, token: dict, buffer_minutes: int = 5) -> bool:
        """检查 token 是否过期"""
        expires_at = token.get("expires_at")
        if not expires_at:
            return True
        try:
            exp_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            buffer = timedelta(minutes=buffer_minutes)
            return exp_time - now < buffer
        except Exception:
            return True

    async def refresh_token(self, account_name: str) -> dict:
        """刷新 Token"""
        token = self.storage.get_token(account_name)
        if not token:
            raise ValueError(f"No token found for account: {account_name}")

        client_id = token.get("client_id")
        client_secret = token.get("client_secret")
        refresh_token = token.get("refresh_token")

        if not all([client_id, client_secret, refresh_token]):
            raise ValueError("Missing client credentials or refresh token")

        payload = {
            "clientId": client_id,
            "clientSecret": client_secret,
            "grantType": "refresh_token",
            "refreshToken": refresh_token,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.REFRESH_URL,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=30.0
                )

            if response.status_code != 200:
                logger.error(f"Token refresh failed: {response.status_code} - {response.text}")
                raise ValueError(f"Token refresh failed: {response.status_code}")

            result = response.json()

            # 更新 token 数据
            expires_in = result.get("expiresIn", 3600)
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            token["access_token"] = result.get("accessToken", token.get("access_token"))
            token["expires_at"] = expires_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            if "refreshToken" in result:
                token["refresh_token"] = result["refreshToken"]

            self.storage.save_token(account_name, token)
            logger.info(f"Token refreshed for {account_name}")

            return {
                "success": True,
                "expires_at": token["expires_at"],
            }

        except httpx.RequestError as e:
            logger.error(f"Token refresh request failed: {e}")
            raise

    async def test_account(self, account_name: str) -> dict:
        """测试账号 - 发送实际对话请求"""
        token = self.storage.get_token(account_name)
        if not token:
            return {"success": False, "error": "No token found"}

        access_token = token.get("access_token")
        if not access_token:
            return {"success": False, "error": "No access token"}

        # 如果 token 过期，先刷新
        if self._is_token_expired(token):
            try:
                await self.refresh_token(account_name)
                token = self.storage.get_token(account_name)
                access_token = token.get("access_token")
            except Exception as e:
                return {"success": False, "error": f"Token refresh failed: {e}"}

        # 先获取 profiles
        profiles = []
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.LIST_PROFILES_URL,
                    json={},
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {access_token}"
                    },
                    timeout=30.0
                )
            if response.status_code == 200:
                result = response.json()
                profiles = [p.get("profileName") for p in result.get("profiles", [])[:5]]
        except Exception as e:
            logger.warning(f"Failed to get profiles: {e}")

        # 发送实际对话请求测试
        try:
            from .api_proxy import handle_non_streaming_request_by_name
            from .models import AnthropicRequest

            test_request = AnthropicRequest(
                model="claude-sonnet-4-20250514",
                max_tokens=100,
                messages=[{"role": "user", "content": "Say 'Hello! Test successful.' in one line."}]
            )

            response = await handle_non_streaming_request_by_name(test_request, account_name)

            # 提取 AI 响应
            ai_response = ""
            if response and "content" in response:
                for block in response.get("content", []):
                    if block.get("type") == "text":
                        ai_response = block.get("text", "")
                        break

            return {
                "success": True,
                "message": "Account is working",
                "profiles": profiles,
                "ai_response": ai_response,
                "model": response.get("model", ""),
                "usage": response.get("usage", {}),
            }

        except Exception as e:
            logger.error(f"Test chat failed: {e}")
            return {
                "success": False,
                "error": f"Chat test failed: {str(e)}",
                "profiles": profiles,
            }


# 全局服务实例
_account_service: Optional[AccountService] = None


def get_account_service() -> AccountService:
    """获取全局账号服务实例"""
    global _account_service
    if _account_service is None:
        _account_service = AccountService()
    return _account_service
