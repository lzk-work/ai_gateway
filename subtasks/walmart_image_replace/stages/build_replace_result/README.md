# build_replace_result

入口：`05_replace_build_result.py`。保留原主图，合并已有及本批次上传成功的新副图，派生图集与图片追踪清单。

详见[业务说明](../../README.md)和[最终设计](../../../../docs/walmart_image_replace_design.md)。路径由版本3批次派生，续跑使用原批次名；原主图不参与替换，线上更新由walmart_api项目负责，本项目不含Feed调用。
