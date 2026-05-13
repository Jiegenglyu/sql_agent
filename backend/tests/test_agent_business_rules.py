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
            patch.object(agent, "chat_completion", side_effect=fake_chat_completion),
            patch.object(agent, "_call_mcp_tool", side_effect=fake_call),
        ):
            response = agent._run_tool_calling_agent(AgentQueryRequest(question="卡时使用率是多少？"), trace)

        self.assertEqual(response.answer, "done")
        self.assertEqual(response.rules[0]["path"], "aiinfra.md")
        self.assertIn("卡时使用率", response.rules[0]["content"])
        self.assertEqual([step.name for step in trace], ["mcp.business_rule_search", "mcp.business_rule_read"])


if __name__ == "__main__":
    unittest.main()
