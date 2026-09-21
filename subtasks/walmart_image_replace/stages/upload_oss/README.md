# upload_oss

入口：`04_replace_upload_sub_oss.py`。仅上传来源SKU目录的唯一计划副图；不限制bucket版本控制，允许记录保存前中断后的同键重复上传。成功checkpoint跳过。

详见[业务说明](../../README.md)和[最终设计](../../../../docs/walmart_image_replace_design.md)。路径由版本3批次派生，续跑使用原批次名；原主图不参与替换，线上更新由walmart_api项目负责，本项目不含Feed调用。
