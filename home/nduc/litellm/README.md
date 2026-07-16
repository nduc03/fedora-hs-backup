# LiteLLM Proxy Service

LiteLLM Proxy là một OpenAI-compatible API gateway cho phép bạn kết nối với 100+ LLM providers thông qua một interface thống nhất.

## Đặc điểm

- **OpenAI-compatible API**: Sử dụng OpenAI SDK để gọi bất kỳ LLM nào
- **100+ LLM providers**: OpenAI, Azure, Anthropic, Cohere, Gemini, Ollama, v.v.
- **Load balancing**: Tự động phân phối request giữa nhiều deployments
- **Rate limiting**: Kiểm soát RPM/TPM cho mỗi model
- **Virtual Keys**: Tạo và quản lý API keys cho từng team/user
- **Spend tracking**: Theo dõi chi phí sử dụng API
- **Cloudflare Tunnel**: Expose qua port 127.0.0.1:18002

## Cài đặt

### 1. Cấu hình API Keys

Chỉnh sửa file `litellm.env` và thêm API keys của các providers bạn muốn sử dụng:

```bash
# OpenAI
OPENAI_API_KEY=sk-...

# Azure OpenAI
AZURE_API_KEY=...
AZURE_API_BASE=https://your-endpoint.openai.azure.com/

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

**QUAN TRỌNG**: 
- Đổi `LITELLM_MASTER_KEY` thành một giá trị bảo mật
- Đổi `LITELLM_SALT_KEY` thành một chuỗi random (KHÔNG được thay đổi sau khi đã setup)

### 2. Cấu hình Models

Chỉnh sửa `config/config.yaml` để thêm/xóa models:

```yaml
model_list:
  - model_name: gpt-4o
    litellm_params:
      model: openai/gpt-4o
      api_key: os.environ/OPENAI_API_KEY
```

### 3. Chạy Installation Script

```bash
chmod +x install.sh
./install.sh
```

### 4. Kiểm tra Service

```bash
systemctl --user status litellm
journalctl --user -u litellm -f
```

## Sử dụng

### Admin UI

Truy cập Admin UI tại: `http://127.0.0.1:18002/ui`

Đăng nhập bằng `LITELLM_MASTER_KEY` từ file `litellm.env`.

### Gọi API

#### Với OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-1234",  # LITELLM_MASTER_KEY
    base_url="http://127.0.0.1:18002"
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
```

#### Với curl

```bash
curl -X POST http://127.0.0.1:18002/v1/chat/completions \
  -H "Authorization: Bearer sk-1234" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### Tạo Virtual Keys

```bash
curl -X POST http://127.0.0.1:18002/key/generate \
  -H "Authorization: Bearer sk-1234" \
  -H "Content-Type: application/json" \
  -d '{
    "models": ["gpt-4o", "claude-3-5-sonnet"],
    "max_budget": 10,
    "budget_duration": "30d"
  }'
```

## Load Balancing

Để load balance giữa nhiều deployments của cùng một model:

1. Thêm nhiều entries với cùng `model_name` trong `config.yaml`
2. Cấu hình `rpm` (requests per minute) cho mỗi deployment
3. LiteLLM sẽ tự động phân phối requests

```yaml
model_list:
  - model_name: gpt-4o
    litellm_params:
      model: azure/gpt-4o-deployment-1
      api_base: https://endpoint1.openai.azure.com/
      api_key: os.environ/AZURE_API_KEY_1
      rpm: 60

  - model_name: gpt-4o
    litellm_params:
      model: azure/gpt-4o-deployment-2
      api_base: https://endpoint2.openai.azure.com/
      api_key: os.environ/AZURE_API_KEY_2
      rpm: 60
```

## Cloudflare Tunnel Setup

Service này expose port `127.0.0.1:18002`. Để setup Cloudflare Tunnel:

```bash
cloudflared tunnel route dns <tunnel-name> litellm.yourdomain.com
```

Thêm vào tunnel config:

```yaml
ingress:
  - hostname: litellm.yourdomain.com
    service: http://127.0.0.1:18002
  - service: http_status:404
```

## Database (Optional)

Để enable virtual keys và spend tracking, uncomment phần database trong `litellm.env`:

```bash
DATABASE_URL=postgresql://user:password@host:port/dbname
```

Và trong `config/config.yaml`:

```yaml
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
```

## Redis (Optional)

Để load balance giữa nhiều LiteLLM instances, thêm Redis config:

```yaml
router_settings:
  redis_host: os.environ/REDIS_HOST
  redis_password: os.environ/REDIS_PASSWORD
  redis_port: 6379
```

## Troubleshooting

### Check logs

```bash
journalctl --user -u litellm -f
```

### Test health endpoint

```bash
curl http://127.0.0.1:18002/health
```

### Restart service

```bash
systemctl --user restart litellm
```

## Links

- [LiteLLM Documentation](https://docs.litellm.ai/)
- [Supported Models](https://docs.litellm.ai/docs/providers)
- [Docker Hub](https://hub.docker.com/r/litellm/litellm)
