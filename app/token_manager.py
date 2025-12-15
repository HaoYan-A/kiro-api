"""
Token 管理模块
负责读取、刷新和管理 Kiro Token
支持从文件配置或新存储系统读取
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, Union

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
    # OIDC Token 刷新 URL
    REFRESH_URL = "https://oidc.us-east-1.amazonaws.com/token"

    def __init__(self):
        self._tokens: Dict[str, TokenData] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._profile_arns: Dict[str, str] = {}  # 缓存 profile_arn
        self._storage = None  # 延迟加载存储模块

    def _get_storage(self):
        """获取存储模块（延迟加载避免循环导入）"""
        if self._storage is None:
            from .storage import get_storage
            self._storage = get_storage()
        return self._storage

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

    def _read_token_from_storage(self, account_name: str) -> Optional[TokenData]:
        """从存储系统读取 token"""
        storage = self._get_storage()
        token_data = storage.get_token(account_name)
        if not token_data:
            return None

        # 转换为 TokenData 格式
        data = {
            "accessToken": token_data.get("access_token", ""),
            "refreshToken": token_data.get("refresh_token", ""),
            "expiresAt": token_data.get("expires_at", ""),
            "clientIdHash": token_data.get("client_id_hash", ""),
        }
        return TokenData(data)

    def _get_client_credentials_from_storage(self, account_name: str) -> dict:
        """从存储系统读取 client credentials"""
        storage = self._get_storage()
        token_data = storage.get_token(account_name)
        if not token_data:
            raise ValueError(f"No token data found for account: {account_name}")

        client_id = token_data.get("client_id")
        client_secret = token_data.get("client_secret")

        if not client_id or not client_secret:
            raise ValueError("Missing client credentials in storage")

        return {"clientId": client_id, "clientSecret": client_secret}

    def _read_client_credentials(self, account: AccountConfig, client_id_hash: str) -> dict:
        """读取 client credentials 文件"""
        token_dir = account.get_token_file_path().parent
        credentials_path = token_dir / f"{client_id_hash}.json"

        if not credentials_path.exists():
            logger.error(f"Client credentials file not found: {credentials_path}")
            raise ValueError(f"Client credentials file not found: {credentials_path}")

        try:
            with open(credentials_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read client credentials: {e}")
            raise

    async def _refresh_token(self, account: AccountConfig, token: TokenData) -> TokenData:
        """刷新 token"""
        config = get_config()
        refresh_url = config.api.refresh_url

        # 读取 client credentials
        if not token.client_id_hash:
            raise ValueError("Token missing clientIdHash, cannot refresh")

        credentials = self._read_client_credentials(account, token.client_id_hash)
        client_id = credentials.get("clientId")
        client_secret = credentials.get("clientSecret")

        if not client_id or not client_secret:
            raise ValueError("Client credentials missing clientId or clientSecret")

        payload = {
            "clientId": client_id,
            "clientSecret": client_secret,
            "grantType": "refresh_token",
            "refreshToken": token.refresh_token,
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
            # OIDC API 返回 expiresIn (秒), 需要转换为 ISO 时间戳
            new_data = token.to_dict().copy()
            new_data["accessToken"] = result.get("accessToken", token.access_token)

            # 计算过期时间
            expires_in = result.get("expiresIn", 3600)
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            new_data["expiresAt"] = expires_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")

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

    async def get_token_by_name(self, account_name: str, force_refresh: bool = False) -> TokenData:
        """
        通过账号名称获取 token（从存储系统读取）

        Args:
            account_name: 账号名称
            force_refresh: 是否强制刷新

        Returns:
            TokenData 实例
        """
        async with self._get_lock(account_name):
            # 从存储系统读取
            token = self._read_token_from_storage(account_name)

            if token is None:
                raise ValueError(f"Failed to read token for account: {account_name}")

            # 检查是否需要刷新
            if force_refresh or token.is_expired():
                logger.info(f"Token for {account_name} is expired or force refresh requested, refreshing...")
                token = await self._refresh_token_by_name(account_name, token)
                self._tokens[account_name] = token
            else:
                self._tokens[account_name] = token

            return token

    async def _refresh_token_by_name(self, account_name: str, token: TokenData) -> TokenData:
        """通过账号名称刷新 token（从存储系统）"""
        # 获取 client credentials
        credentials = self._get_client_credentials_from_storage(account_name)
        client_id = credentials.get("clientId")
        client_secret = credentials.get("clientSecret")

        payload = {
            "clientId": client_id,
            "clientSecret": client_secret,
            "grantType": "refresh_token",
            "refreshToken": token.refresh_token,
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
                logger.error(f"Token refresh failed with status {response.status_code}: {response.text}")
                raise ValueError(f"Token refresh failed: {response.status_code}")

            result = response.json()

            # 计算过期时间
            expires_in = result.get("expiresIn", 3600)
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            # 更新存储
            storage = self._get_storage()
            token_data = storage.get_token(account_name) or {}
            token_data["access_token"] = result.get("accessToken", token.access_token)
            token_data["expires_at"] = expires_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            if "refreshToken" in result:
                token_data["refresh_token"] = result["refreshToken"]

            storage.save_token(account_name, token_data)
            logger.info(f"Token refreshed successfully for {account_name}")

            # 返回新的 TokenData
            new_data = {
                "accessToken": token_data["access_token"],
                "refreshToken": token_data.get("refresh_token", token.refresh_token),
                "expiresAt": token_data["expires_at"],
                "clientIdHash": token_data.get("client_id_hash", token.client_id_hash),
            }
            return TokenData(new_data)

        except httpx.RequestError as e:
            logger.error(f"Token refresh request failed: {e}")
            raise

    async def fetch_profile_arn_by_name(self, account_name: str) -> str:
        """
        通过账号名称获取 profile_arn（从存储系统）

        Args:
            account_name: 账号名称

        Returns:
            profile_arn 字符串
        """
        # 检查缓存
        if account_name in self._profile_arns:
            return self._profile_arns[account_name]

        # 获取 token
        token = await self.get_token_by_name(account_name)

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
                raise ValueError(f"No profiles found for account: {account_name}")

            # 使用第一个 profile
            profile_arn = profiles[0].get("arn", "")
            if not profile_arn:
                raise ValueError(f"Profile ARN not found in response")

            # 缓存结果
            self._profile_arns[account_name] = profile_arn
            logger.info(f"Fetched profile_arn for {account_name}: {profile_arn}")

            return profile_arn

        except httpx.RequestError as e:
            logger.error(f"Failed to fetch profile_arn: {e}")
            raise


# 全局 TokenManager 实例
_token_manager: Optional[TokenManager] = None


def get_token_manager() -> TokenManager:
    """获取全局 TokenManager 实例"""
    global _token_manager
    if _token_manager is None:
        _token_manager = TokenManager()
    return _token_manager
