# build_report

入口：`08_replace_build_report.py`。输出最新使用、新生成及待归档三份XLSX/JSONL；新生成及待归档主图列空。

详见[业务说明](../../README.md)和[最终设计](../../../../docs/walmart_image_replace_design.md)。路径由版本3批次派生，续跑使用原批次名；原主图不参与替换，线上更新由walmart_api项目负责，本项目不含Feed调用。
