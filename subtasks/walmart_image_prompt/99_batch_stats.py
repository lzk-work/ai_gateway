"""Print current Walmart batch statistics."""

from __future__ import annotations

import argparse

from scripts.statistics.batch_stats import print_batch_stats


def main() -> None:
    parser = argparse.ArgumentParser(description="99 批次统计")
    parser.add_argument("--batch-name", default=None, help="手动指定批次名；不填则按业务入参 Excel 文件名确定。")
    args = parser.parse_args()
    print_batch_stats(args.batch_name)


if __name__ == "__main__":
    main()
