"""Example direct call through the framework."""

from ai_gateway.clients.gateway_client import GatewayClient
from ai_gateway.config.loader import load_app_config
from ai_gateway.models import AiTask, ImageInput

config = load_app_config("configs/gateways.yaml", "configs/models.yaml")
client = GatewayClient(config)

task = AiTask(
    task_id="demo-001",
    prompt="请识别这张图片中的主要内容，并用中文简短回答。",
    images=[ImageInput(type="url", value="https://example.com/image.jpg")],
)

result = client.call(task)
print(result.status)
print(result.text or result.error_message)
