# Kiro API

A Python proxy server that converts Anthropic Claude API requests to AWS CodeWhisperer, enabling you to use Claude models through Kiro authentication.

## Features

- 🔄 **Anthropic API Compatible** - Drop-in replacement for Anthropic API
- 👥 **Multi-Account Support** - Configure multiple Kiro accounts with custom API keys
- 🔐 **Auto Token Refresh** - Automatically refreshes tokens before expiration
- 🌊 **Streaming Support** - Full support for SSE streaming responses
- 🐳 **Docker Ready** - Easy deployment with Docker Compose

## Inspiration

This project is inspired by [kiro2cc](https://github.com/bestK/kiro2cc), a Go implementation of Kiro token management and API proxy. This Python version adds multi-account support and improved token management.

## Quick Start

### Prerequisites

- Python 3.12+ or Docker
- Kiro authentication token (from `~/.aws/sso/cache/kiro-auth-token.json`)

### Installation

```bash
git clone https://github.com/YOUR_USERNAME/kiro-api.git
cd kiro-api
pip install -r requirements.txt
```

### Configuration

1. Copy the example config:
```bash
cp config.example.yaml config.yaml
```

2. Edit `config.yaml` with your settings:
```yaml
accounts:
  - name: "your-name"
    api_key: "sk-kiro-your-name-your-secret-key"
    token_file: "~/.aws/sso/cache/kiro-auth-token.json"
    profile_arn: "arn:aws:codewhisperer:us-east-1:YOUR_ACCOUNT:profile/YOUR_PROFILE"
```

### Run

**Direct:**
```bash
python server.py
```

**Docker:**
```bash
docker-compose up -d
```

## Usage

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/claude/v1/messages` | POST | Anthropic API proxy |
| `/v1/messages` | POST | Anthropic API proxy (alias) |
| `/health` | GET | Health check |

### Example Request

```bash
curl http://localhost:8080/claude/v1/messages \
  -H "x-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4-5",
    "max_tokens": 100,
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### Streaming Request

```bash
curl http://localhost:8080/claude/v1/messages \
  -H "x-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4-5",
    "max_tokens": 100,
    "stream": true,
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## Supported Models

| Anthropic Model | Mapped To |
|-----------------|-----------|
| `claude-sonnet-4-5` | `claude-sonnet-4.5` |
| `claude-sonnet-4-20250514` | `claude-sonnet-4.5` |
| `claude-opus-4-5` | `claude-opus-4.5` |
| `claude-opus-4-5-20251101` | `claude-opus-4.5` |
| `claude-3-5-haiku-20241022` | `claude-sonnet-4.5` |

## Scripts

```bash
# Print all configured API keys and token status
python scripts/print_keys.py
```

## Docker Commands

```bash
# Build and start
docker-compose up -d --build

# View logs
docker-compose logs -f

# Stop
docker-compose down

# Restart
docker-compose restart
```

## Project Structure

```
kiro-api/
├── app/
│   ├── api_proxy.py        # API proxy logic
│   ├── config.py           # Configuration management
│   ├── models.py           # Data models
│   ├── request_converter.py # Request conversion
│   ├── response_parser.py  # Binary response parsing
│   └── token_manager.py    # Token management
├── scripts/
│   └── print_keys.py       # Print API keys utility
├── config.yaml             # Configuration file
├── config.example.yaml     # Example configuration
├── server.py               # Main server entry
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## License

MIT

## Acknowledgments

- [kiro2cc](https://github.com/bestK/kiro2cc) - Original Go implementation
