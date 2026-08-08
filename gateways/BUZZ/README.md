# BUZZ 中转站接入说明

## 1. 平台定位

BUZZ 是一个兼容 Anthropic Messages API 的 AI 中转站。接入时主要替换 API Base URL 和 API Key，业务层可以按 Claude Messages API 的格式调用。

文档：

- Quickstart: https://buzzai.cc/docs/guides/quickstart
- OpenAI SDK with BUZZ: https://buzzai.cc/docs/guides/openai-sdk

## 2. 基础信息

- Base URL: `https://buzzai.cc`
- Anthropic Messages endpoint: `POST https://buzzai.cc/v1/messages`
- Models endpoint: `GET https://buzzai.cc/v1/models`

## 3. 鉴权方式

BUZZ 支持以下 Header：

```http
Authorization: Bearer $BUZZ_API_KEY
```

或：

```http
x-api-key: $BUZZ_API_KEY
```

建议系统内部统一从项目本地配置文件读取：

```text
E:\WorkSpace\ai_gateway\configs\local.env
```

内容：

```env
BUZZ_API_KEY=sk-xxx
```

程序启动时会自动读取 `configs/local.env`，无需手动设置 Windows 系统环境变量。

## 4. 文本调用示例

```bash
curl -X POST https://buzzai.cc/v1/messages \
  -H "x-api-key: $BUZZ_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{
    "model": "claude-haiku-4-5-20251001",
    "max_tokens": 80,
    "messages": [
      {"role": "user", "content": "reply with exactly: hello world"}
    ]
  }'
```

## 5. 图片 URL + 文本识别

BUZZ 兼容 Anthropic Messages API。图片 URL 可作为 image content block 传入，由模型结合提示词返回文本结果。

```bash
curl -X POST https://buzzai.cc/v1/messages \
  -H "x-api-key: $BUZZ_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{
    "model": "claude-sonnet-5",
    "max_tokens": 1024,
    "messages": [
      {
        "role": "user",
        "content": [
          {
            "type": "image",
            "source": {
              "type": "url",
              "url": "https://example.com/image.jpg"
            }
          },
          {
            "type": "text",
            "text": "请识别这张图片中的商品、文字和明显属性，并用中文输出。"
          }
        ]
      }
    ]
  }'
```

## 6. base64 图片 + 文本识别

如果图片 URL 有防盗链、登录权限、过期签名，建议调用方先下载图片并转成 base64，再传给 BUZZ。

```json
{
  "type": "image",
  "source": {
    "type": "base64",
    "media_type": "image/png",
    "data": "base64-image-content"
  }
}
```

## 7. Python SDK 示例

```python
from anthropic import Anthropic
import os

client = Anthropic(
    base_url="https://buzzai.cc",
    api_key=os.environ["BUZZ_API_KEY"],
)

message = client.messages.create(
    model="claude-sonnet-5",
    max_tokens=1024,
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "url",
                        "url": "https://example.com/image.jpg",
                    },
                },
                {
                    "type": "text",
                    "text": "请识别图片内容并返回中文结果。",
                },
            ],
        }
    ],
)

print(message.content[0].text)
```

## 8. 响应解析

Anthropic Messages API 的文本通常在：

```text
response.content[0].text
```

如果返回多个 content block，应拼接所有 `type = text` 的内容。

## 9. 常见错误

| 错误 | 含义 | 建议处理 |
| --- | --- | --- |
| 401 buzz_error | API Key 缺失或无效 | 检查环境变量和 Header |
| 403 permission_error | Key 被禁用或 IP 白名单不匹配 | 检查 BUZZ 后台配置 |
| 503 model_not_found | 当前渠道组无可用模型 | 调用 `/v1/models` 查看模型 |
| 429 | 限流 | 延迟重试 |
| 5xx | 中转站或上游异常 | 重试，必要时切备用网关 |

## 10. 模型列表

```bash
curl https://buzzai.cc/v1/models \
  -H "Authorization: Bearer $BUZZ_API_KEY"
```

系统启动时可以缓存模型列表，也可以在模型不可用时动态刷新。

## 11. 适配器配置建议

```yaml
buzz:
  type: anthropic_compatible
  base_url: https://buzzai.cc
  messages_endpoint: /v1/messages
  models_endpoint: /v1/models
  api_key_env: BUZZ_API_KEY
  auth_header: x-api-key
  supports:
    text: true
    image_url: true
    image_base64: true
  timeout_seconds: 120
  max_retries: 3
```

## 12. 接入注意事项

- 图片 URL 必须能被公网访问。
- 如果 URL 有防盗链或登录限制，优先转 base64。
- 批量图片识别时要控制并发，避免触发限流。
- 记录 task_id、gateway、model、latency_ms、status、error_code，便于追踪问题。
- 模型名称以后可能变化，应放在配置中，不要硬编码在业务代码里。
