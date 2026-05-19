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

    def test_prepares_context_by_reading_rule_context_and_schema_overview(self) -> None:
        trace = []
        calls = []

        def fake_call(name, arguments):
            calls.append((name, arguments))
            if name == "current_date_context":
                return {"today": "2026-05-14", "timezone": "Asia/Shanghai"}
            if name == "business_rule_context":
                return {
                    "question": arguments["question"],
                    "rule_count": 2,
                    "rules": [
                        {
                            "path": "resource_pools.md",
                            "schema": "aiinfra",
                            "table": "resource_pools",
                            "content": "join_keys: resource_pools.pool_type = gpu_card_models.pool_type",
                        }
                    ],
                }
            if name == "pg_schema_overview":
                return {
                    "tables": [
                        {"schema": "aiinfra", "table": "resource_pools"},
                        {"schema": "aiinfra", "table": "gpu_card_models"},
                    ],
                    "table_count": 2,
                }
            raise AssertionError(f"unexpected tool call: {name}")

        with patch.object(agent, "_call_mcp_tool", side_effect=fake_call):
            prepared = agent._prepare_query_context(
                AgentQueryRequest(question="上周每个团队的单卡时成本是多少？"),
                trace,
                language="zh",
            )

        self.assertEqual(prepared["schema"]["table_count"], 2)
        self.assertIn("join_keys", prepared["rules"][0]["content"])
        self.assertEqual([name for name, _ in calls], ["current_date_context", "business_rule_context", "pg_schema_overview"])

    def test_orchestrated_agent_reports_sql_validation_error_without_fallback(self) -> None:
        trace = []

        def fake_call(name, arguments):
            if name == "current_date_context":
                return {"today": "2026-05-14", "timezone": "Asia/Shanghai"}
            if name == "business_rule_context":
                return {"rules": [{"path": "resource_pools.md", "content": "table: resource_pools"}]}
            if name == "pg_schema_overview":
                return {"tables": [{"schema": "aiinfra", "table": "resource_pools"}], "table_count": 1}
            if name == "pg_validate_sql":
                return {"ok": False, "reason": "Only SELECT or read-only WITH queries are allowed.", "limited_sql": None}
            raise AssertionError(f"unexpected tool call: {name}")

        with (
            patch.object(agent, "_call_mcp_tool", side_effect=fake_call),
            patch.object(agent, "generate_sql", return_value="DELETE FROM aiinfra.resource_pools"),
        ):
            response = agent._run_orchestrated_agent(AgentQueryRequest(question="查一下资源池"), trace)

        self.assertEqual(response.status, "error")
        self.assertEqual(response.error["code"], "sql_validation_error")
        self.assertFalse(response.executed)
        self.assertEqual(response.sql, "DELETE FROM aiinfra.resource_pools")
        self.assertNotEqual(response.sql, "SELECT 1 AS agent_ready")
        self.assertEqual(trace[-1].name, "mcp.pg_validate_sql")


if __name__ == "__main__":
    unittest.main()
