"""
配置管理模块
负责加载和管理 config.yaml 配置文件
"""
import os
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


class AccountConfig(BaseModel):
    """账号配置"""
    name: str
    api_key: str
    token_file: str
    profile_arn: str

    def get_token_file_path(self) -> Path:
        """获取 token 文件的绝对路径"""
        return Path(self.token_file).expanduser()


class ServerConfig(BaseModel):
    """服务器配置"""
    host: str = "0.0.0.0"
    port: int = 8080


class ApiConfig(BaseModel):
    """API 配置"""
    codewhisperer_url: str = "https://q.us-east-1.amazonaws.com/generateAssistantResponse"
    refresh_url: str = "https://prod.us-east-1.auth.desktop.kiro.dev/refreshToken"


class AppConfig(BaseModel):
    """应用配置"""
    server: ServerConfig = Field(default_factory=ServerConfig)
    accounts: List[AccountConfig] = Field(default_factory=list)
    model_mapping: Dict[str, str] = Field(default_factory=dict)
    api: ApiConfig = Field(default_factory=ApiConfig)

    def get_account_by_api_key(self, api_key: str) -> Optional[AccountConfig]:
        """通过 API Key 查找账号"""
        for account in self.accounts:
            if account.api_key == api_key:
                return account
        return None

    def get_account_by_name(self, name: str) -> Optional[AccountConfig]:
        """通过名称查找账号"""
        for account in self.accounts:
            if account.name == name:
                return account
        return None

    def map_model(self, model: str) -> str:
        """模型名称映射"""
        return self.model_mapping.get(model, model)


# 全局配置实例
_config: Optional[AppConfig] = None


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """
    加载配置文件

    Args:
        config_path: 配置文件路径，默认为项目根目录下的 config.yaml

    Returns:
        AppConfig 实例
    """
    global _config

    if config_path is None:
        # 默认配置文件路径：项目根目录下的 config.yaml
        config_path = Path(__file__).parent.parent / "config.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    _config = AppConfig(**data)
    return _config


def get_config() -> AppConfig:
    """获取全局配置实例"""
    global _config
    if _config is None:
        _config = load_config()
    return _config
