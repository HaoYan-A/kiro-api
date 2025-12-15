"""
Kiro API Server
Anthropic API 代理服务，支持多账号配置
"""
import argparse
import logging
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from app.api_proxy import handle_non_streaming_request, handle_streaming_request
from app.config import get_config, load_config
from app.models import AnthropicRequest

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 创建 FastAPI 应用
app = FastAPI(
    title="Kiro API",
    description="Anthropic API Proxy for AWS CodeWhisperer",
    version="1.0.0"
)


@app.on_event("startup")
async def startup_event():
    """启动事件"""
    config = get_config()
    logger.info(f"Kiro API Server starting...")
    logger.info(f"Loaded {len(config.accounts)} account(s)")
    for account in config.accounts:
        logger.info(f"  - {account.name}: {account.api_key[:20]}...")


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok"}


@app.post("/claude/v1/messages")
@app.post("/v1/messages")
async def messages_endpoint(
    request: Request,
    x_api_key: str = Header(None, alias="x-api-key"),
    authorization: str = Header(None)
):
    """
    Anthropic Messages API 代理端点

    支持两种认证方式：
    - x-api-key header
    - Authorization: Bearer <api_key>
    """
    config = get_config()

    # 提取 API Key
    api_key = x_api_key
    if not api_key and authorization:
        if authorization.startswith("Bearer "):
            api_key = authorization[7:]

    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    # 查找账号
    account = config.get_account_by_api_key(api_key)
    if not account:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # 解析请求体
    try:
        body = await request.json()
        anthropic_req = AnthropicRequest(**body)
    except Exception as e:
        logger.error(f"Failed to parse request body: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid request body: {e}")

    # 验证模型
    mapped_model = config.map_model(anthropic_req.model)
    if not mapped_model:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or unsupported model: {anthropic_req.model}"
        )

    logger.info(f"Request from account '{account.name}', model: {anthropic_req.model} -> {mapped_model}, stream: {anthropic_req.stream}")

    # 处理请求
    try:
        if anthropic_req.stream:
            # 流式响应
            return StreamingResponse(
                handle_streaming_request(anthropic_req, account),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"
                }
            )
        else:
            # 非流式响应
            response = await handle_non_streaming_request(anthropic_req, account)
            return JSONResponse(content=response)

    except Exception as e:
        logger.error(f"Request processing failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Kiro API Server")
    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)"
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=None,
        help="Server port (overrides config file)"
    )
    parser.add_argument(
        "-H", "--host",
        default=None,
        help="Server host (overrides config file)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode"
    )

    args = parser.parse_args()

    # 加载配置
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path(__file__).parent / config_path

    try:
        config = load_config(str(config_path))
    except FileNotFoundError:
        logger.error(f"Configuration file not found: {config_path}")
        sys.exit(1)

    # 确定服务器参数
    host = args.host or config.server.host
    port = args.port or config.server.port

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # 打印启动信息
    print(f"\n{'='*60}")
    print(f"Kiro API Server")
    print(f"{'='*60}")
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"Config: {config_path}")
    print(f"\nAvailable endpoints:")
    print(f"  POST /claude/v1/messages - Anthropic API proxy")
    print(f"  POST /v1/messages        - Anthropic API proxy (alias)")
    print(f"  GET  /health             - Health check")
    print(f"\nConfigured accounts:")
    for account in config.accounts:
        print(f"  - {account.name}: {account.api_key}")
    print(f"{'='*60}\n")

    # 启动服务器
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="debug" if args.debug else "info"
    )


if __name__ == "__main__":
    main()
