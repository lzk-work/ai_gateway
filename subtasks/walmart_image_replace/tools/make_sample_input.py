"""Generate a blank replacement input workbook; never overwrite an existing file."""
import argparse
from pathlib import Path
from openpyxl import Workbook
HEADER = ['来源SKU','结果SKU','店铺','标题','五点','参考主图链接',*[f'参考副图链接{i}' for i in range(1,7)],'已有主图链接',*[f'已有副图链接{i}' for i in range(1,7)],'GTIN','商品类型']
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(Path(__file__).resolve().parents[1]/'input/image_replace_jiushi-test.xlsx'))
    args = parser.parse_args()
    path = Path(args.output)
    if path.exists():
        raise SystemExit('Input already exists; refusing to overwrite')
    path.parent.mkdir(parents=True,exist_ok=True)
    wb = Workbook()
    wb.active.title = 'Sheet1'
    wb.active.append(HEADER)
    wb.active.freeze_panes = 'A2'
    wb.save(path)
    print(path)
