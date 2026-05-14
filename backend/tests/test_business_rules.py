import tempfile
import unittest
from pathlib import Path

from backend.app.services.business_rules import BusinessRuleError, read_rule, resolve_business_rules, search_rules


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

    def test_resolve_returns_fixed_logic_and_only_matched_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "daily_gpu_metrics.md").write_text(
                "\n".join(
                    [
                        "# daily_gpu_metrics",
                        "schema: usage",
                        "table: daily_gpu_metrics",
                        "aliases: 卡时, 成本",
                        "related_tables: usage.teams",
                        "",
                        "### 固定查询逻辑 ###",
                        "- 默认使用最新 metric_date。",
                        "- 比率计算必须避免除以零。",
                        "",
                        "### 业务逻辑 ###",
                        "## 卡时使用率",
                        "keywords: 卡时使用率, 使用率",
                        "- 卡时使用率 = allocated / total。",
                        "",
                        "## 单卡时成本",
                        "keywords: 单卡时成本, 成本",
                        "- 单卡时成本 = cost_usd / allocated_gpu_hours。",
                    ]
                ),
                encoding="utf-8",
            )
            (base / "gpu_nodes.md").write_text(
                "\n".join(
                    [
                        "# gpu_nodes",
                        "schema: usage",
                        "table: gpu_nodes",
                        "",
                        "### 固定查询逻辑 ###",
                        "- active 表示可用。",
                        "",
                        "### 业务逻辑 ###",
                        "## 总卡数",
                        "keywords: 总卡数",
                        "- 总卡数 = SUM(gpu_count)。",
                    ]
                ),
                encoding="utf-8",
            )

            resolved = resolve_business_rules("上周每个团队的单卡时成本是多少？", base_dir=base)

            self.assertFalse(resolved["clarification_required"])
            self.assertEqual(resolved["candidates"][0]["path"], "daily_gpu_metrics.md")
            self.assertIn("默认使用最新", resolved["candidates"][0]["fixed_logic"])
            self.assertEqual(resolved["candidates"][0]["matched_sections"][0]["title"], "单卡时成本")
            self.assertNotIn("卡时使用率", resolved["candidates"][0]["matched_sections"][0]["content"])
            selected_tables = {(item["schema"], item["table"]) for item in resolved["selected_tables"]}
            self.assertIn(("usage", "daily_gpu_metrics"), selected_tables)
            self.assertIn(("usage", "teams"), selected_tables)

    def test_resolve_asks_clarification_for_generic_usage_question(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "daily_gpu_metrics.md").write_text(
                "\n".join(
                    [
                        "# daily_gpu_metrics",
                        "schema: usage",
                        "table: daily_gpu_metrics",
                        "",
                        "### 固定查询逻辑 ###",
                        "- 默认使用最新 metric_date。",
                        "",
                        "### 业务逻辑 ###",
                        "## 卡时使用率",
                        "keywords: 使用情况, 卡时使用率",
                        "- 卡时使用率 = allocated / total。",
                        "",
                        "## GPU/NPU 核心利用率",
                        "keywords: 使用情况, 核心利用率",
                        "- 核心利用率 = avg_gpu_utilization_pct。",
                    ]
                ),
                encoding="utf-8",
            )

            resolved = resolve_business_rules("查一下使用情况", base_dir=base)

            self.assertTrue(resolved["clarification_required"])
            labels = [option["label"] for option in resolved["options"]]
            self.assertIn("卡时使用率", labels)
            self.assertIn("GPU/NPU 核心利用率", labels)

    def test_resolve_reports_no_structured_rules_without_loading_legacy_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "legacy.md").write_text("卡时使用率 = 已分配卡时 / 总卡时。", encoding="utf-8")

            resolved = resolve_business_rules("卡时使用率", base_dir=base)

            self.assertEqual(resolved["reason"], "no_structured_rules")
            self.assertEqual(resolved["candidates"], [])


if __name__ == "__main__":
    unittest.main()
