"""Local MCP tools backed by the same HTTP API as the web application.

Uses Model Context Protocol Python SDK 1.26.0 (MIT):
https://github.com/modelcontextprotocol/python-sdk/tree/v1.26.0
Run from the project root: python -m backend.app.mcp_server
"""

import httpx
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("测试知识与用例助手")
API_ROOT = "http://127.0.0.1:8000"


def request_api(method: str, path: str, body: dict | None = None):
    # Local calls must not inherit an external HTTP proxy.
    with httpx.Client(timeout=120.0, trust_env=False) as client:
        response = client.request(method, API_ROOT + path, json=body)
    if response.is_error:
        raise RuntimeError(f"后端 HTTP {response.status_code}: {response.text}")
    return response.json()


@mcp.tool()
def list_sources() -> list[dict]:
    """列出本机知识资料的标题、版本、来源与编号。"""
    return request_api("GET", "/api/sources")


@mcp.tool()
def generate_test_cases(requirement: str, source_ids: list[int]) -> dict:
    """按需求与所选资料生成测试用例草稿，结果需由人工核对。"""
    return request_api("POST", "/api/case-batches/generate", {
        "requirement": requirement,
        "source_ids": source_ids,
    })


@mcp.tool()
def review_test_cases(batch_id: int) -> dict:
    """对已有批次进行 AI 审查，批次编号来自生成结果。"""
    return request_api("POST", f"/api/case-batches/{batch_id}/review")


if __name__ == "__main__":
    mcp.run(transport="stdio")
