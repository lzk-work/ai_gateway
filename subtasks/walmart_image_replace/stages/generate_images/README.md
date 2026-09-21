# generate_images

入口：`03_replace_generate_sub_images.py`。仅提交、查询和下载副图，复用已保存task_id；下载429单图延后。

详见[业务说明](../../README.md)和[最终设计](../../../../docs/walmart_image_replace_design.md)。路径由版本3批次派生，续跑使用原批次名；原主图不参与替换，线上更新由walmart_api项目负责，本项目不含Feed调用。
