# query_existing_images

入口：`01_replace_inventory.py`。读取输入、校验副图并创建或加载计划，不扫描OSS目录。

详见[业务说明](../../README.md)和[最终设计](../../../../docs/walmart_image_replace_design.md)。路径由版本3批次派生，续跑使用原批次名；原主图不参与替换，线上更新由walmart_api项目负责，本项目不含Feed调用。
