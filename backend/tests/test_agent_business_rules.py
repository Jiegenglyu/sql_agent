import unittest
from unittest.mock import patch

from backend.app.models import AgentQueryRequest
from backend.app.services import agent


class AgentBusinessRuleExpansionTests(unittest.TestCase):
    def test_expands_search_hit_with_rule_read_window(self) -> None:
        trace = []
        calls = []

        def fake_call(name, arguments):
            calls.append((name, arguments))
            if name == "business_rule_read":
                return {
                    "path": arguments["path"],
                    "content": "- 中文口径：卡时使用率 = 已分配卡时 / 总卡时。",
                    "start_line": arguments["start_line"],
                    "end_line": arguments["end_line"],
                    "line_count": 20,
                    "truncated": False,
                    "snippets": [{"line": arguments["start_line"], "text": "## Card-Hours"}],
                }
            raise AssertionError(f"unexpected tool call: {name}")

        with patch.object(agent, "_call_mcp_tool", side_effect=fake_call):
            expanded = agent._read_relevant_business_rules(
                trace,
                [{"path": "aiinfra.md", "score": 10, "snippets": [{"line": 5, "text": "卡时使用率"}]}],
                max_files=1,
            )

        self.assertEqual(
            calls,
            [("business_rule_read", {"path": "aiinfra.md", "start_line": 2, "end_line": 15})],
        )
        self.assertEqual(trace[0].name, "mcp.business_rule_read")
        self.assertEqual(expanded[0]["path"], "aiinfra.md")
        self.assertIn("卡时使用率", expanded[0]["content"])
        self.assertEqual(expanded[0]["read_start_line"], 2)
        self.assertEqual(expanded[0]["read_end_line"], 15)

    def test_tool_calling_search_result_is_expanded_with_rule_read(self) -> None:
        trace = []
        chat_calls = []

        def fake_chat_completion(**kwargs):
            chat_calls.append(kwargs)
            if len(chat_calls) == 1:
                return {
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "function": {
                                "name": "business_rule_search",
                                "arguments": '{"query": "卡时使用率", "limit": 8}',
                            },
                        }
                    ]
                }
            return {"content": "done"}

        def fake_call(name, arguments):
            if name == "business_rule_search":
                return [{"path": "aiinfra.md", "score": 10, "snippets": [{"line": 5, "text": "卡时使用率"}]}]
            if name == "business_rule_read":
                return {
                    "path": arguments["path"],
                    "content": "- 中文口径：卡时使用率 = 已分配卡时 / 总卡时。",
                    "start_line": arguments["start_line"],
                    "end_line": arguments["end_line"],
                    "line_count": 20,
                    "truncated": False,
                    "snippets": [{"line": arguments["start_line"], "text": "## Card-Hours"}],
                }
            raise AssertionError(f"unexpected tool call: {name}")

        with (
            patch.object(
                agent,
                "_prepare_query_context",
                return_value={
                    "date_context": {},
                    "rules": [],
                    "schema": {"tables": [], "table_count": 0},
                    "clarification_response": None,
                },
            ),
            patch.object(agent, "chat_completion", side_effect=fake_chat_completion),
            patch.object(agent, "_call_mcp_tool", side_effect=fake_call),
        ):
            response = agent._run_tool_calling_agent(AgentQueryRequest(question="卡时使用率是多少？"), trace)

        self.assertEqual(response.answer, "done")
        self.assertEqual(response.rules[0]["path"], "aiinfra.md")
        self.assertIn("卡时使用率", response.rules[0]["content"])
        self.assertEqual([step.name for step in trace], ["mcp.business_rule_search", "mcp.business_rule_read"])

    def test_prepares_context_with_selected_tables_without_schema_overview(self) -> None:
        trace = []
        calls = []

        def fake_call(name, arguments):
            calls.append((name, arguments))
            if name == "current_date_context":
                return {"today": "2026-05-14", "timezone": "Asia/Shanghai"}
            if name == "business_rule_resolve":
                return {
                    "clarification_required": False,
                    "reason": "confident_match",
                    "confidence": 0.9,
                    "candidates": [
                        {
                            "path": "daily_gpu_metrics.md",
                            "schema": "usage",
                            "table": "daily_gpu_metrics",
                            "score": 42,
                            "fixed_logic": "- 默认使用最新 metric_date。",
                            "matched_sections": [
                                {
                                    "title": "单卡时成本",
                                    "content": "- 单卡时成本 = cost_usd / allocated_gpu_hours。",
                                    "score": 30,
                                }
                            ],
                            "snippets": [{"line": 10, "text": "单卡时成本"}],
                        }
                    ],
                    "selected_tables": [
                        {
                            "schema": "usage",
                            "table": "daily_gpu_metrics",
                            "role": "primary",
                            "source_path": "daily_gpu_metrics.md",
                            "reason": "business_rule_match",
                        }
                    ],
                }
            if name == "pg_describe_table":
                return {
                    "schema": arguments["schema"],
                    "table": arguments["table"],
                    "table_type": "BASE TABLE",
                    "estimated_rows": 10,
                    "comment": None,
                    "columns": [{"column_name": "cost_usd"}, {"column_name": "allocated_gpu_hours"}],
                    "indexes": [],
                    "error": None,
                }
            raise AssertionError(f"unexpected tool call: {name}")

        with patch.object(agent, "_call_mcp_tool", side_effect=fake_call):
            prepared = agent._prepare_query_context(
                AgentQueryRequest(question="上周每个团队的单卡时成本是多少？"),
                trace,
                language="zh",
            )

        self.assertIsNone(prepared["clarification_response"])
        self.assertEqual(prepared["schema"]["table_count"], 1)
        self.assertIn("默认使用最新", prepared["rules"][0]["content"])
        self.assertNotIn("pg_schema_overview", [name for name, _ in calls])

    def test_orchestrated_agent_returns_clarification_without_sql(self) -> None:
        trace = []

        def fake_call(name, arguments):
            if name == "current_date_context":
                return {"today": "2026-05-14", "timezone": "Asia/Shanghai"}
            if name == "business_rule_resolve":
                return {
                    "clarification_required": True,
                    "reason": "low_confidence",
                    "confidence": 0.5,
                    "candidates": [],
                    "selected_tables": [],
                    "options": [
                        {"label": "卡时使用率", "table": "usage.daily_gpu_metrics"},
                        {"label": "GPU/NPU 核心利用率", "table": "usage.device_utilization"},
                    ],
                }
            raise AssertionError(f"unexpected tool call: {name}")

        with patch.object(agent, "_call_mcp_tool", side_effect=fake_call):
            response = agent._run_orchestrated_agent(AgentQueryRequest(question="查一下使用情况"), trace)

        self.assertFalse(response.executed)
        self.assertEqual(response.sql, "")
        self.assertIn("你想看哪一种", response.answer)
        self.assertIn("卡时使用率", response.answer)
        self.assertEqual(trace[-1].name, "clarification")


if __name__ == "__main__":
    unittest.main()
