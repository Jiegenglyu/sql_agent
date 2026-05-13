import tempfile
import unittest
from pathlib import Path

from backend.app.services.business_rules import BusinessRuleError, read_rule, search_rules


class BusinessRuleSearchTests(unittest.TestCase):
    def test_search_only_allowed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "gpu.md").write_text("AI infra total card count uses gpu_count.", encoding="utf-8")
            (base / "ignored.py").write_text("AI infra secret", encoding="utf-8")

            results = search_rules("AI infra card count", base_dir=base, limit=5, max_file_bytes=1000)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["path"], "gpu.md")

    def test_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "rules"
            base.mkdir()
            outside = Path(tmp) / "secret.md"
            outside.write_text("secret", encoding="utf-8")

            with self.assertRaises(BusinessRuleError):
                read_rule("../secret.md", base_dir=base, max_file_bytes=1000)

    def test_reads_relative_rule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "billing.md").write_text("Use invoice status = paid.", encoding="utf-8")

            rule = read_rule("billing.md", base_dir=base, max_file_bytes=1000)

            self.assertEqual(rule["path"], "billing.md")
            self.assertIn("invoice", rule["content"])

    def test_search_selects_file_then_reads_matching_rule_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "aiinfra.md").write_text(
                "\n".join(
                    [
                        "# AI Infra",
                        "",
                        "## Card-Hours",
                        "- 中文口径：卡时使用率 = 已分配卡时 / 总卡时。",
                        "- SQL 字段：allocated_gpu_hours 和 idle_gpu_hours。",
                    ]
                ),
                encoding="utf-8",
            )
            (base / "finance.md").write_text(
                "\n".join(
                    [
                        "# Finance",
                        "",
                        "## Collection",
                        "- 中文口径：回款金额只统计 paid invoice。",
                    ]
                ),
                encoding="utf-8",
            )

            results = search_rules("最新一天各集群的卡时使用率是多少", base_dir=base, limit=5, max_file_bytes=1000)
            hit_line = results[0]["snippets"][0]["line"]
            rule = read_rule(
                results[0]["path"],
                base_dir=base,
                start_line=hit_line,
                end_line=hit_line + 1,
                max_file_bytes=1000,
            )

            self.assertEqual(results[0]["path"], "aiinfra.md")
            self.assertIn("卡时使用率", rule["content"])
            self.assertNotIn("回款金额", rule["content"])

    def test_searches_chinese_terms_with_ngrams(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "aiinfra.md").write_text("卡时使用率 = 已分配卡时 / 总卡时。", encoding="utf-8")

            results = search_rules("最新一天各集群的卡时使用率是多少", base_dir=base, limit=5, max_file_bytes=1000)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["path"], "aiinfra.md")


if __name__ == "__main__":
    unittest.main()
