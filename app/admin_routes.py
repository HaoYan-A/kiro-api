"""
管理 API 路由
提供账号管理的 RESTful API
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasicCredentials
from pydantic import BaseModel

from .account_service import get_account_service
from .auth import get_current_user, security

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])


# 请求/响应模型
class AccountCreate(BaseModel):
    """创建账号请求"""
    name: str
    api_key: Optional[str] = None


class AccountUpdate(BaseModel):
    """更新账号请求"""
    api_key: Optional[str] = None
    enabled: Optional[bool] = None


class TokenUpdate(BaseModel):
    """更新 Token 请求"""
    access_token: str
    refresh_token: str
    expires_at: str
    client_id_hash: str
    client_id: str
    client_secret: str


class AccountResponse(BaseModel):
    """账号响应"""
    name: str
    api_key: str
    enabled: bool
    has_token: Optional[bool] = None
    expires_at: Optional[str] = None
    is_expired: Optional[bool] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ApiResponse(BaseModel):
    """通用 API 响应"""
    success: bool
    message: str
    data: Optional[dict] = None


# 路由
@router.get("/accounts", response_model=List[AccountResponse])
async def list_accounts(
    credentials: HTTPBasicCredentials = Depends(security)
):
    """列出所有账号"""
    await get_current_user(credentials)
    service = get_account_service()
    accounts = service.list_accounts()
    return accounts


@router.get("/accounts/{name}")
async def get_account(
    name: str,
    credentials: HTTPBasicCredentials = Depends(security)
):
    """获取账号详情"""
    await get_current_user(credentials)
    service = get_account_service()
    account = service.get_account(name)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.post("/accounts", response_model=AccountResponse)
async def create_account(
    data: AccountCreate,
    credentials: HTTPBasicCredentials = Depends(security)
):
    """创建账号"""
    await get_current_user(credentials)
    service = get_account_service()
    try:
        account = service.create_account(data.name, data.api_key)
        return account
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/accounts/{name}", response_model=AccountResponse)
async def update_account(
    name: str,
    data: AccountUpdate,
    credentials: HTTPBasicCredentials = Depends(security)
):
    """更新账号"""
    await get_current_user(credentials)
    service = get_account_service()

    updates = {}
    if data.api_key is not None:
        updates["api_key"] = data.api_key
    if data.enabled is not None:
        updates["enabled"] = data.enabled

    account = service.update_account(name, updates)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.delete("/accounts/{name}", response_model=ApiResponse)
async def delete_account(
    name: str,
    credentials: HTTPBasicCredentials = Depends(security)
):
    """删除账号"""
    await get_current_user(credentials)
    service = get_account_service()
    success = service.delete_account(name)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return ApiResponse(success=True, message=f"Account '{name}' deleted")


@router.post("/accounts/{name}/toggle", response_model=AccountResponse)
async def toggle_account(
    name: str,
    credentials: HTTPBasicCredentials = Depends(security)
):
    """切换账号启用/停用状态"""
    await get_current_user(credentials)
    service = get_account_service()
    account = service.toggle_account(name)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.post("/accounts/{name}/token", response_model=ApiResponse)
async def update_token(
    name: str,
    data: TokenUpdate,
    credentials: HTTPBasicCredentials = Depends(security)
):
    """更新账号的 Token 数据"""
    await get_current_user(credentials)
    service = get_account_service()

    # 检查账号是否存在
    account = service.get_account(name)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    token_data = {
        "access_token": data.access_token,
        "refresh_token": data.refresh_token,
        "expires_at": data.expires_at,
        "client_id_hash": data.client_id_hash,
        "client_id": data.client_id,
        "client_secret": data.client_secret,
    }

    service.save_token(name, token_data)
    return ApiResponse(success=True, message=f"Token updated for '{name}'")


@router.post("/accounts/{name}/refresh", response_model=ApiResponse)
async def refresh_token(
    name: str,
    credentials: HTTPBasicCredentials = Depends(security)
):
    """刷新账号的 Token"""
    await get_current_user(credentials)
    service = get_account_service()

    # 检查账号是否存在
    account = service.get_account(name)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        result = await service.refresh_token(name)
        return ApiResponse(
            success=True,
            message=f"Token refreshed for '{name}'",
            data=result
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/accounts/{name}/test", response_model=ApiResponse)
async def test_account(
    name: str,
    credentials: HTTPBasicCredentials = Depends(security)
):
    """测试账号"""
    await get_current_user(credentials)
    service = get_account_service()

    # 检查账号是否存在
    account = service.get_account(name)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    result = await service.test_account(name)
    return ApiResponse(
        success=result.get("success", False),
        message=result.get("message", result.get("error", "Unknown error")),
        data=result
    )


@router.get("/check-auth")
async def check_auth(
    credentials: HTTPBasicCredentials = Depends(security)
):
    """检查认证状态"""
    user = await get_current_user(credentials)
    return {"authenticated": True, "username": user}
