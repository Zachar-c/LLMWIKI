import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend.app import mcp_server


ROOT = Path(__file__).resolve().parents[2]


class McpContractTests(unittest.TestCase):
    def test_generation_and_review_send_exact_contract(self):
        with patch.object(mcp_server, "request_api", return_value={"id": 3}) as call:
            self.assertEqual(mcp_server.generate_test_cases("登录需求", [1, 2]), {"id": 3})
            call.assert_called_once_with("POST", "/api/case-batches/generate", {"requirement": "登录需求", "source_ids": [1, 2]})
        with patch.object(mcp_server, "request_api", return_value={"status": "reviewed"}) as call:
            self.assertEqual(mcp_server.review_test_cases(3), {"status": "reviewed"})
            call.assert_called_once_with("POST", "/api/case-batches/3/review")

    def test_backend_http_error_is_not_reported_as_success(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(503, json={"detail": "模型未配置"}))
        real_client = httpx.Client
        with patch.object(mcp_server.httpx, "Client", side_effect=lambda **kwargs: real_client(transport=transport)):
            with self.assertRaisesRegex(RuntimeError, 'HTTP 503.*模型未配置'):
                mcp_server.request_api("GET", "/api/sources")


class McpStdioIntegrationTests(unittest.TestCase):
    def test_sdk_handshake_and_real_source_list(self):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", 8000))
            except OSError:
                self.skipTest("端口 8000 已被占用；不连接或停止已有服务")
        with tempfile.TemporaryDirectory() as directory:
            env = os.environ.copy()
            env["KNOWLEDGE_DB_PATH"] = str(Path(directory) / "mcp-test.sqlite3")
            backend = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000"],
                cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            try:
                for _ in range(60):
                    if backend.poll() is not None:
                        self.fail(f"本轮测试后端启动失败：{backend.stderr.read().decode(errors='replace')}")
                    try:
                        response = httpx.get("http://127.0.0.1:8000/api/health", timeout=0.5, trust_env=False)
                        if response.status_code == 200:
                            break
                    except (httpx.ConnectError, httpx.ConnectTimeout):
                        pass
                    time.sleep(0.1)
                else:
                    self.fail("本轮测试后端未启动")

                with httpx.Client(trust_env=False) as client:
                    created = client.post("http://127.0.0.1:8000/api/sources", json={
                        "title": "MCP 自编测试资料", "origin": "测试", "version": "v1", "content": "只用于测试的公开示例。"
                    })
                    self.assertEqual(created.status_code, 201)
                    expected_sources = client.get("http://127.0.0.1:8000/api/sources").json()

                async def call_mcp():
                    params = StdioServerParameters(command=sys.executable, args=["-m", "backend.app.mcp_server"], cwd=ROOT)
                    async with stdio_client(params) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            tools = await session.list_tools()
                            self.assertTrue({"list_sources", "generate_test_cases", "review_test_cases"}.issubset({tool.name for tool in tools.tools}))
                            result = await session.call_tool("list_sources", {})
                            self.assertFalse(result.isError)
                            missing = await session.call_tool("review_test_cases", {"batch_id": 2147483647})
                            self.assertTrue(missing.isError)
                            self.assertIn("HTTP 404", missing.content[0].text)
                            return result

                result = asyncio.run(call_mcp())
                self.assertIsNotNone(result.structuredContent)
                self.assertEqual(result.structuredContent, {"result": expected_sources})
            finally:
                backend.terminate()
                backend.wait(timeout=10)
                backend.stderr.close()


if __name__ == "__main__":
    unittest.main()
