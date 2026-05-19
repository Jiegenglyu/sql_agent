import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.mcp import public_server
from backend.app.models import AgentQueryResponse, TokenUsage, TraceStep


API_KEY = "sk-1234"


class PublicMcpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings_patcher = patch.object(
            public_server,
            "get_settings",
            return_value=SimpleNamespace(mcp_api_keys=[API_KEY]),
        )
        self.settings_patcher.start()
        self.call_log_patcher = patch.object(public_server, "append_mcp_call")
        self.call_log_patcher.start()

    def tearDown(self) -> None:
        self.call_log_patcher.stop()
        self.settings_patcher.stop()

    def test_public_mcp_registers_public_tools_and_capability_resource(self) -> None:
        tools = asyncio.run(public_server.mcp.list_tools())
        resources = asyncio.run(public_server.mcp.list_resources())

        self.assertEqual([tool.name for tool in tools], ["describe_capabilities", "ask_agent"])
        ask_tool = next(tool for tool in tools if tool.name == "ask_agent")
        self.assertIn("Current business capability summary", ask_tool.description)
        self.assertEqual([str(resource.uri) for resource in resources], ["capabilities://sql-agent"])

    def test_describe_capabilities_returns_summary(self) -> None:
        with patch.object(
            public_server,
            "public_capabilities",
            return_value={"summary": "可以查询卡时使用率。", "generated_by": "llm", "rule_count": 1, "topics": []},
        ) as capabilities:
            result = public_server.describe_capabilities(api_key=API_KEY, language="zh", refresh=True)

        capabilities.assert_called_once_with(language="zh", use_llm=True, refresh=True)
        self.assertEqual(result["summary"], "可以查询卡时使用率。")

    def test_ask_agent_returns_structured_public_surface(self) -> None:
        agent_response = AgentQueryResponse(
            question="今天的卡时使用率多少？",
            answer="今天的卡时使用率是 82%。",
            sql="SELECT * FROM private_table",
            executed=True,
            trace=[
                TraceStep(
                    name="mcp.pg_query",
                    status="success",
                    summary="Readonly query returned 1 row.",
                    detail={"sql": "SELECT * FROM private_table"},
                )
            ],
            rules=[{"path": "daily_gpu_metrics.md", "table": "daily_gpu_metrics"}],
            db_schema={"tables": [{"schema": "aiinfra", "table": "daily_gpu_metrics"}]},
            validation={"ok": True, "limited_sql": "SELECT * FROM private_table LIMIT 5"},
            result={"columns": ["rate"], "rows": [{"rate": 0.82}], "row_count": 1, "limited_sql": "..."},
            token_usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15, requests=2),
        )

        with patch.object(public_server, "run_agent_query", return_value=agent_response) as run_agent:
            result = public_server.ask_agent("今天的卡时使用率多少？", api_key=API_KEY, language="zh", max_rows=5)

        request = run_agent.call_args.args[0]
        self.assertEqual(request.question, "今天的卡时使用率多少？")
        self.assertTrue(request.execute)
        self.assertEqual(request.language, "zh")
        self.assertEqual(request.max_rows, 5)

        self.assertEqual(
            result,
            {
                "question": "今天的卡时使用率多少？",
                "caller": "unknown",
                "answer": "今天的卡时使用率是 82%。",
                "status": "success",
                "executed": True,
                "needs_clarification": False,
                "row_count": 1,
                "result": {
                    "columns": ["rate"],
                    "rows": [{"rate": 0.82}],
                    "row_count": 1,
                    "sql": "SELECT * FROM private_table",
                    "limited_sql": "...",
                    "source_tables": ["aiinfra.daily_gpu_metrics"],
                },
                "error": None,
                "trace": [
                    {
                        "name": "mcp.pg_query",
                        "status": "success",
                        "summary": "Readonly query returned 1 row.",
                        "detail": {"sql": "SELECT * FROM private_table"},
                    }
                ],
                "rules": [{"path": "daily_gpu_metrics.md", "table": "daily_gpu_metrics"}],
                "schema": {"tables": [{"schema": "aiinfra", "table": "daily_gpu_metrics"}]},
                "token_usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "requests": 2,
                },
            },
        )

    def test_ask_agent_can_return_capability_summary_without_querying(self) -> None:
        with (
            patch.object(public_server, "run_agent_query") as run_agent,
            patch.object(
                public_server,
                "public_capabilities",
                return_value={
                    "summary": "这个 Agent 可以查询卡时使用率和容量告警。",
                    "generated_by": "fallback",
                    "rule_count": 2,
                    "topics": ["卡时使用率", "容量告警"],
                },
            ),
        ):
            result = public_server.ask_agent("你能查什么？", api_key=API_KEY, language="zh")

        run_agent.assert_not_called()
        self.assertFalse(result["executed"])
        self.assertEqual(result["answer"], "这个 Agent 可以查询卡时使用率和容量告警。")
        self.assertIn("capabilities", result)

    def test_ask_agent_accepts_runtime_dict_token_usage(self) -> None:
        agent_response = AgentQueryResponse(
            question="今天的卡时使用率多少？",
            answer="今天的卡时使用率来自 `aiinfra.daily_gpu_metrics` 表，是 82%。",
            sql="",
            executed=True,
            trace=[],
            rules=[],
            db_schema=None,
            validation={"ok": True},
            result={"columns": [], "rows": [], "row_count": 1, "limited_sql": "..."},
        ).model_copy(
            update={
                "token_usage": {
                    "prompt_tokens": "10",
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "requests": 2,
                }
            }
        )

        with patch.object(public_server, "run_agent_query", return_value=agent_response):
            result = public_server.ask_agent("今天的卡时使用率多少？", api_key=API_KEY)

        self.assertEqual(
            result["token_usage"],
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "requests": 2},
        )
        self.assertIn("aiinfra.daily_gpu_metrics", result["answer"])

    def test_ask_agent_exposes_trace_and_source_tables_for_debugging(self) -> None:
        agent_response = AgentQueryResponse(
            question="查一下使用情况",
            answer=(
                "我需要先澄清一下。我理解这个问题可能指以下几类：\n"
                "1. 卡时使用率：aiinfra.daily_gpu_metrics\n"
                "2. GPU 核心利用率：aiinfra.gpu_nodes\n"
                "你想看哪一种？"
            ),
            sql="",
            executed=False,
            trace=[
                TraceStep(
                    name="clarification",
                    status="warning",
                    summary="Question is ambiguous.",
                    detail={},
                )
            ],
            rules=[],
            db_schema={"tables": [{"schema": "aiinfra", "table": "daily_gpu_metrics"}]},
            validation={"ok": False},
            result=None,
        )

        with patch.object(public_server, "run_agent_query", return_value=agent_response):
            result = public_server.ask_agent("查一下使用情况", api_key=API_KEY)

        self.assertTrue(result["needs_clarification"])
        self.assertIn("aiinfra.daily_gpu_metrics", result["answer"])
        self.assertEqual(result["trace"][0]["name"], "clarification")
        self.assertEqual(result["result"], None)

    def test_ask_agent_rejects_unknown_language(self) -> None:
        with self.assertRaises(ValueError):
            public_server.ask_agent("hello", api_key=API_KEY, language="fr")

    def test_ask_agent_rejects_invalid_api_key(self) -> None:
        result = public_server.ask_agent("查一下资源池", api_key="wrong")

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "auth_failed")


if __name__ == "__main__":
    unittest.main()
