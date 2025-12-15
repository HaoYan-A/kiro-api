# Kiro API

A Python proxy server that converts Anthropic Claude API requests to AWS CodeWhisperer, enabling you to use Claude models through Kiro authentication.

## Features

- 🔄 **Anthropic API Compatible** - Drop-in replacement for Anthropic API
- 👥 **Multi-Account Support** - Configure multiple Kiro accounts with custom API keys
- 🌐 **Web Admin Panel** - Manage accounts via browser interface
- 🔐 **Auto Token Refresh** - Automatically refreshes tokens before expiration
- 🔑 **Auto Profile Discovery** - Automatically fetches AWS profile ARN from API
- 🌊 **Streaming Support** - Full support for SSE streaming responses
- 🐳 **Docker Ready** - Easy deployment with Docker Compose

## Inspiration

This project is inspired by [kiro2cc](https://github.com/bestK/kiro2cc), a Go implementation of Kiro token management and API proxy. This Python version adds multi-account support, web admin panel, and improved token management.

## Quick Start

### Docker (Recommended)

```bash
git clone https://github.com/HaoYan-A/kiro-api.git
cd kiro-api
docker-compose up -d --build
```

Access:
- **Admin Panel**: http://localhost:8080/
- **API Endpoint**: http://localhost:8080/v1/messages

### Manual Installation

```bash
git clone https://github.com/HaoYan-A/kiro-api.git
cd kiro-api
pip install -r requirements.txt
python server.py
```

## Web Admin Panel

The web admin panel allows you to manage accounts without editing configuration files.

### Login

- Default credentials: `admin` / `admin123`
- Customize via environment variables: `ADMIN_USERNAME` and `ADMIN_PASSWORD`

### Features

- **Add Account**: Upload token files (drag & drop supported)
  - `~/.aws/sso/cache/kiro-auth-token.json`
  - `~/.aws/sso/cache/{clientIdHash}.json`
- **Test Account**: Send a test chat request and see AI response
- **Refresh Token**: Manually refresh expired tokens
- **Enable/Disable**: Toggle account availability
- **Delete**: Remove accounts

## API Endpoints

| Endpoint | Auth | Description |
|----------|------|-------------|
| `/v1/messages` | x-api-key | Anthropic API proxy |
| `/claude/v1/messages` | x-api-key | Anthropic API proxy (alias) |
| `/health` | None | Health check |
| `/admin/*` | Basic Auth | Admin API |
| `/` | None | Web admin panel |

## Usage Examples

### Chat Request

```bash
curl http://localhost:8080/v1/messages \
  -H "x-api-key: sk-kiro-your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4-20250514",
    "max_tokens": 100,
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### Streaming Request

```bash
curl http://localhost:8080/v1/messages \
  -H "x-api-key: sk-kiro-your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4-20250514",
    "max_tokens": 100,
    "stream": true,
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_USERNAME` | admin | Admin panel username |
| `ADMIN_PASSWORD` | admin123 | Admin panel password |

### Docker Compose

```yaml
services:
  kiro-api:
    build: .
    ports:
      - "8080:8080"
    volumes:
      - ./data:/app/data          # Persist accounts & tokens
      - ./config.yaml:/app/config.yaml:ro
    environment:
      - ADMIN_USERNAME=admin
      - ADMIN_PASSWORD=your_secure_password
```

### Config File (Optional)

You can also configure accounts via `config.yaml`:

```yaml
accounts:
  - name: "your-name"
    api_key: "sk-kiro-your-name-your-secret-key"
    token_file: "~/.aws/sso/cache/kiro-auth-token.json"
```

## Supported Models

| Anthropic Model | Mapped To |
|-----------------|-----------|
| `claude-sonnet-4-20250514` | `claude-sonnet-4.5` |
| `claude-sonnet-4-5` | `claude-sonnet-4.5` |
| `claude-opus-4-5-20251101` | `claude-opus-4.5` |
| `claude-opus-4-5` | `claude-opus-4.5` |
| `claude-3-5-haiku-20241022` | `claude-sonnet-4.5` |

## Project Structure

```
kiro-api/
├── app/
│   ├── account_service.py  # Account management service
│   ├── admin_routes.py     # Admin API routes
│   ├── api_proxy.py        # API proxy logic
│   ├── auth.py             # Authentication module
│   ├── config.py           # Configuration management
│   ├── models.py           # Data models
│   ├── storage.py          # JSON file storage
│   └── token_manager.py    # Token management
├── web/                    # Frontend source (Vite + React)
├── static/                 # Built frontend assets
├── data/                   # Accounts & tokens storage
├── server.py               # Main server entry
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
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

## License

MIT

## Acknowledgments

- [kiro2cc](https://github.com/bestK/kiro2cc) - Original Go implementation
