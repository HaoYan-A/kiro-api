"""
存储模块
使用本地 JSON 文件存储账号和 Token 数据
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 默认数据目录
DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"


class Storage:
    """JSON 文件存储服务"""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self.accounts_file = self.data_dir / "accounts.json"
        self.tokens_dir = self.data_dir / "tokens"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """确保目录存在"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.tokens_dir.mkdir(parents=True, exist_ok=True)
        if not self.accounts_file.exists():
            self._save_accounts({"accounts": []})

    def _load_accounts(self) -> dict:
        """加载账号配置"""
        try:
            with open(self.accounts_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load accounts: {e}")
            return {"accounts": []}

    def _save_accounts(self, data: dict) -> None:
        """保存账号配置"""
        try:
            with open(self.accounts_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save accounts: {e}")
            raise

    # 账号操作
    def list_accounts(self) -> List[dict]:
        """列出所有账号"""
        data = self._load_accounts()
        return data.get("accounts", [])

    def get_account(self, name: str) -> Optional[dict]:
        """获取单个账号"""
        accounts = self.list_accounts()
        for account in accounts:
            if account.get("name") == name:
                return account
        return None

    def get_account_by_api_key(self, api_key: str) -> Optional[dict]:
        """通过 API Key 获取账号"""
        accounts = self.list_accounts()
        for account in accounts:
            if account.get("api_key") == api_key and account.get("enabled", True):
                return account
        return None

    def create_account(self, account: dict) -> dict:
        """创建账号"""
        data = self._load_accounts()
        accounts = data.get("accounts", [])

        # 检查名称唯一性
        for existing in accounts:
            if existing.get("name") == account.get("name"):
                raise ValueError(f"Account with name '{account['name']}' already exists")
            if existing.get("api_key") == account.get("api_key"):
                raise ValueError(f"API Key already in use")

        now = datetime.now(timezone.utc).isoformat()
        account["created_at"] = now
        account["updated_at"] = now
        account.setdefault("enabled", True)

        accounts.append(account)
        data["accounts"] = accounts
        self._save_accounts(data)
        return account

    def update_account(self, name: str, updates: dict) -> Optional[dict]:
        """更新账号"""
        data = self._load_accounts()
        accounts = data.get("accounts", [])

        for i, account in enumerate(accounts):
            if account.get("name") == name:
                # 不允许修改名称
                updates.pop("name", None)
                updates.pop("created_at", None)
                updates["updated_at"] = datetime.now(timezone.utc).isoformat()
                accounts[i].update(updates)
                data["accounts"] = accounts
                self._save_accounts(data)
                return accounts[i]
        return None

    def delete_account(self, name: str) -> bool:
        """删除账号"""
        data = self._load_accounts()
        accounts = data.get("accounts", [])

        original_len = len(accounts)
        accounts = [a for a in accounts if a.get("name") != name]

        if len(accounts) < original_len:
            data["accounts"] = accounts
            self._save_accounts(data)
            # 同时删除 token 文件
            token_file = self.tokens_dir / f"{name}.json"
            if token_file.exists():
                token_file.unlink()
            return True
        return False

    def toggle_account(self, name: str) -> Optional[dict]:
        """切换账号启用/停用状态"""
        account = self.get_account(name)
        if account:
            new_enabled = not account.get("enabled", True)
            return self.update_account(name, {"enabled": new_enabled})
        return None

    # Token 操作
    def get_token(self, account_name: str) -> Optional[dict]:
        """获取账号的 Token 数据"""
        token_file = self.tokens_dir / f"{account_name}.json"
        if not token_file.exists():
            return None
        try:
            with open(token_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load token for {account_name}: {e}")
            return None

    def save_token(self, account_name: str, token_data: dict) -> None:
        """保存账号的 Token 数据"""
        token_file = self.tokens_dir / f"{account_name}.json"
        try:
            with open(token_file, "w", encoding="utf-8") as f:
                json.dump(token_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save token for {account_name}: {e}")
            raise

    def delete_token(self, account_name: str) -> bool:
        """删除账号的 Token 数据"""
        token_file = self.tokens_dir / f"{account_name}.json"
        if token_file.exists():
            token_file.unlink()
            return True
        return False


# 全局存储实例
_storage: Optional[Storage] = None


def get_storage() -> Storage:
    """获取全局存储实例"""
    global _storage
    if _storage is None:
        _storage = Storage()
    return _storage
