"""Example call with JSON result validation."""

from ai_gateway.clients.gateway_client import GatewayClient
from ai_gateway.config.loader import load_app_config
from ai_gateway.models import AiTask, ImageInput
from ai_gateway.validators.result_validator import validate_result

config = load_app_config("configs/gateways.yaml", "configs/models.yaml")
client = GatewayClient(config)

task = AiTask(
    task_id="validated-001",
    prompt=(
        "请识别图片中的商品信息，只返回 JSON，不要输出解释文字。"
        "格式：{\"title\":\"商品标题\",\"brand\":\"品牌或空字符串\",\"confidence\":0.0}"
    ),
    images=[ImageInput(type="url", value="https://example.com/image.jpg")],
    response_template={
        "type": "object",
        "required": ["title", "brand", "confidence"],
        "properties": {
            "title": {"type": "string"},
            "brand": {"type": "string"},
            "confidence": {"type": "number"},
        },
    },
)

result = client.call(task)
result = validate_result(result, task)
print(result.text)
print(result.validation_status)
print(result.validation_errors)
