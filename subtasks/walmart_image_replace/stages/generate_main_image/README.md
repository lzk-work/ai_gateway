# generate_main_image

入口：`03b_replace_generate_main_images.py`。已禁用：本次主图原样保留，不生成或上传。

详见[业务说明](../../README.md)和[最终设计](../../../../docs/walmart_image_replace_design.md)。路径由版本3批次派生，续跑使用原批次名；原主图不参与替换，线上更新由walmart_api项目负责，本项目不含Feed调用。
