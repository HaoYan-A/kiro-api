"""
Token 管理模块
负责读取、刷新和管理 Kiro Token
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import httpx

from .config import AccountConfig, get_config

logger = logging.getLogger(__name__)


class TokenData:
    """Token 数据"""

    def __init__(self, data: dict):
        self.access_token: str = data.get("accessToken", "")
        self.refresh_token: str = data.get("refreshToken", "")
        self.expires_at: str = data.get("expiresAt", "")
        self.client_id_hash: str = data.get("clientIdHash", "")
        self.auth_method: str = data.get("authMethod", "")
        self.provider: str = data.get("provider", "")
        self.region: str = data.get("region", "")
        self._raw_data = data

    def is_expired(self, buffer_minutes: int = 5) -> bool:
        """
        检查 token 是否过期或即将过期

        Args:
            buffer_minutes: 提前多少分钟认为过期

        Returns:
            True 表示已过期或即将过期
        """
        if not self.expires_at:
            return True

        try:
            # 解析 ISO 8601 格式时间
            expires_at = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            # 提前 buffer_minutes 分钟刷新
            buffer_seconds = buffer_minutes * 60
            return (expires_at.timestamp() - now.timestamp()) < buffer_seconds
        except Exception as e:
            logger.warning(f"Failed to parse expires_at: {self.expires_at}, error: {e}")
            return True

    def time_until_expiry(self) -> Optional[str]:
        """返回距离过期的时间字符串"""
        if not self.expires_at:
            return None

        try:
            expires_at = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            delta = expires_at - now

            if delta.total_seconds() < 0:
                return "Expired"

            hours, remainder = divmod(int(delta.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            return f"{hours}h {minutes}m"
        except Exception:
            return None

    def to_dict(self) -> dict:
        """转换为字典"""
        return self._raw_data


class TokenManager:
    """Token 管理器"""

    # ListAvailableProfiles API URL
    LIST_PROFILES_URL = "https://q.us-east-1.amazonaws.com/ListAvailableProfiles"

    def __init__(self):
        self._tokens: Dict[str, TokenData] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._profile_arns: Dict[str, str] = {}  # 缓存 profile_arn

    def _get_lock(self, account_name: str) -> asyncio.Lock:
        """获取账号对应的锁"""
        if account_name not in self._locks:
            self._locks[account_name] = asyncio.Lock()
        return self._locks[account_name]

    async def get_token(self, account: AccountConfig, force_refresh: bool = False) -> TokenData:
        """
        获取账号的 token，自动处理刷新

        Args:
            account: 账号配置
            force_refresh: 是否强制刷新

        Returns:
            TokenData 实例
        """
        async with self._get_lock(account.name):
            # 首先尝试从文件读取
            token = self._read_token_from_file(account)

            if token is None:
                raise ValueError(f"Failed to read token for account: {account.name}")

            # 检查是否需要刷新
            if force_refresh or token.is_expired():
                logger.info(f"Token for {account.name} is expired or force refresh requested, refreshing...")
                token = await self._refresh_token(account, token)
                self._tokens[account.name] = token
            else:
                self._tokens[account.name] = token

            return token

    def _read_token_from_file(self, account: AccountConfig) -> Optional[TokenData]:
        """从文件读取 token"""
        token_path = account.get_token_file_path()

        if not token_path.exists():
            logger.error(f"Token file not found: {token_path}")
            return None

        try:
            with open(token_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return TokenData(data)
        except Exception as e:
            logger.error(f"Failed to read token file {token_path}: {e}")
            return None

    async def _refresh_token(self, account: AccountConfig, token: TokenData) -> TokenData:
        """刷新 token"""
        config = get_config()
        refresh_url = config.api.refresh_url

        payload = {
            "refreshToken": token.refresh_token,
            "clientIdHash": token.client_id_hash,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    refresh_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=30.0
                )

            if response.status_code != 200:
                logger.error(f"Token refresh failed with status {response.status_code}: {response.text}")
                raise ValueError(f"Token refresh failed: {response.status_code}")

            result = response.json()

            # 更新 token 数据
            new_data = token.to_dict().copy()
            new_data["accessToken"] = result.get("accessToken", token.access_token)
            new_data["expiresAt"] = result.get("expiresAt", token.expires_at)
            if "refreshToken" in result:
                new_data["refreshToken"] = result["refreshToken"]

            new_token = TokenData(new_data)

            # 写回文件
            self._save_token_to_file(account, new_token)

            logger.info(f"Token refreshed successfully for {account.name}")
            return new_token

        except httpx.RequestError as e:
            logger.error(f"Token refresh request failed: {e}")
            raise

    def _save_token_to_file(self, account: AccountConfig, token: TokenData) -> None:
        """保存 token 到文件"""
        token_path = account.get_token_file_path()

        try:
            with open(token_path, "w", encoding="utf-8") as f:
                json.dump(token.to_dict(), f, indent=2)
            logger.info(f"Token saved to {token_path}")
        except Exception as e:
            logger.error(f"Failed to save token to {token_path}: {e}")

    async def fetch_profile_arn(self, account: AccountConfig) -> str:
        """
        自动获取账号的 profile_arn

        Args:
            account: 账号配置

        Returns:
            profile_arn 字符串
        """
        # 检查缓存
        if account.name in self._profile_arns:
            return self._profile_arns[account.name]

        # 获取 token
        token = await self.get_token(account)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.LIST_PROFILES_URL,
                    json={},
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {token.access_token}"
                    },
                    timeout=30.0
                )

            if response.status_code != 200:
                logger.error(f"ListAvailableProfiles failed: {response.status_code} - {response.text}")
                raise ValueError(f"Failed to fetch profile_arn: {response.status_code}")

            result = response.json()
            profiles = result.get("profiles", [])

            if not profiles:
                raise ValueError(f"No profiles found for account: {account.name}")

            # 使用第一个 profile
            profile_arn = profiles[0].get("arn", "")
            if not profile_arn:
                raise ValueError(f"Profile ARN not found in response")

            # 缓存结果
            self._profile_arns[account.name] = profile_arn
            logger.info(f"Fetched profile_arn for {account.name}: {profile_arn}")

            return profile_arn

        except httpx.RequestError as e:
            logger.error(f"Failed to fetch profile_arn: {e}")
            raise

    def get_cached_profile_arn(self, account_name: str) -> Optional[str]:
        """获取缓存的 profile_arn"""
        return self._profile_arns.get(account_name)


# 全局 TokenManager 实例
_token_manager: Optional[TokenManager] = None


def get_token_manager() -> TokenManager:
    """获取全局 TokenManager 实例"""
    global _token_manager
    if _token_manager is None:
        _token_manager = TokenManager()
    return _token_manager
