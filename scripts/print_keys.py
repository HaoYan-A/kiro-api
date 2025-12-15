#!/usr/bin/env python3
"""
打印所有配置的 API Key 和 Token 状态
"""
import json
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.config import load_config
from app.token_manager import TokenData


def print_keys():
    """打印所有 API Key"""
    # 加载配置
    config_path = project_root / "config.yaml"
    try:
        config = load_config(str(config_path))
    except FileNotFoundError:
        print(f"Error: Configuration file not found: {config_path}")
        sys.exit(1)

    # 打印头部
    print()
    print("╔" + "═" * 62 + "╗")
    print("║" + " Kiro API Keys".center(62) + "║")
    print("╠" + "═" * 62 + "╣")

    # 打印每个账号
    for account in config.accounts:
        print("║" + f" Account: {account.name}".ljust(62) + "║")
        print("║" + f"   API Key: {account.api_key}".ljust(62) + "║")

        # 读取 token 状态
        token_path = account.get_token_file_path()
        if token_path.exists():
            try:
                with open(token_path, "r") as f:
                    data = json.load(f)
                token = TokenData(data)

                if token.is_expired():
                    status = "✗ Expired"
                else:
                    time_left = token.time_until_expiry()
                    status = f"✓ Valid (expires in {time_left})" if time_left else "✓ Valid"

                print("║" + f"   Status: {status}".ljust(62) + "║")
            except Exception as e:
                print("║" + f"   Status: ✗ Error reading token: {e}".ljust(62) + "║")
        else:
            print("║" + f"   Status: ✗ Token file not found".ljust(62) + "║")

        print("║" + " " * 62 + "║")

    print("╚" + "═" * 62 + "╝")

    # 打印使用示例
    print("\nUsage:")
    if config.accounts:
        account = config.accounts[0]
        print(f'''
  # Non-streaming request
  curl http://localhost:{config.server.port}/claude/v1/messages \\
    -H "x-api-key: {account.api_key}" \\
    -H "Content-Type: application/json" \\
    -d '{{"model":"claude-sonnet-4-5","max_tokens":100,"messages":[{{"role":"user","content":"hi"}}]}}'

  # Streaming request
  curl http://localhost:{config.server.port}/claude/v1/messages \\
    -H "x-api-key: {account.api_key}" \\
    -H "Content-Type: application/json" \\
    -d '{{"model":"claude-sonnet-4-5","max_tokens":100,"stream":true,"messages":[{{"role":"user","content":"hi"}}]}}'
''')


if __name__ == "__main__":
    print_keys()
