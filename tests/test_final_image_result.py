from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "subtasks/walmart_image_prompt"
sys.path.insert(0, str(TASK))

from final_image_result import compact_sub_images


class FinalImageResultTests(unittest.TestCase):
    def test_successful_sub_images_are_compacted_without_gaps(self):
        row = {
            "SKU": "sku-1",
            "处理后主图": "main",
            "处理后附图1": "",
            "处理后附图2": "sub2",
            "处理后附图3": "sub3",
            "处理后附图4": "",
            "处理后附图5": "sub5",
            "处理后附图6": "sub6",
        }

        result = compact_sub_images(row)

        self.assertEqual(result["处理后主图"], "main")
        self.assertEqual(
            [result[f"处理后附图{index}"] for index in range(1, 7)],
            ["sub2", "sub3", "sub5", "sub6", "", ""],
        )


if __name__ == "__main__":
    unittest.main()
