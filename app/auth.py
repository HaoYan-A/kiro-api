"""
认证模块
提供管理界面的简单密码认证
"""
import os
import secrets
from typing import Optional

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

# 环境变量配置
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

security = HTTPBasic()


def verify_credentials(credentials: HTTPBasicCredentials) -> bool:
    """验证用户名密码"""
    correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    return correct_username and correct_password


async def get_current_user(credentials: HTTPBasicCredentials) -> str:
    """获取当前用户（验证凭证）"""
    if not verify_credentials(credentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def check_auth(request: Request) -> Optional[str]:
    """检查请求是否已认证（用于手动检查）"""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Basic "):
        return None

    import base64
    try:
        encoded = auth_header[6:]
        decoded = base64.b64decode(encoded).decode("utf-8")
        username, password = decoded.split(":", 1)

        if secrets.compare_digest(username, ADMIN_USERNAME) and \
           secrets.compare_digest(password, ADMIN_PASSWORD):
            return username
    except Exception:
        pass

    return None
