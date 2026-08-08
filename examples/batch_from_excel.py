"""Example batch call through the framework."""

from ai_gateway.clients.gateway_client import GatewayClient
from ai_gateway.config.loader import load_app_config
from ai_gateway.inputs.excel_input import load_tasks_from_excel
from ai_gateway.jobs.batch_runner import BatchRunner
from ai_gateway.logging.jsonl_logger import JsonlLogger
from ai_gateway.outputs.csv_output import write_results_csv

config = load_app_config("configs/gateways.yaml", "configs/models.yaml")
client = GatewayClient(config)
logger = JsonlLogger("logs/batch_demo.jsonl")
runner = BatchRunner(client, logger=logger)

tasks = load_tasks_from_excel("data/tasks.xlsx")
results = runner.run(tasks, concurrency=3)
write_results_csv(results, "data/results.csv")
