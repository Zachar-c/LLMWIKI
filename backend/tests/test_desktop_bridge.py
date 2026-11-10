import asyncio
import json
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
from fastapi.testclient import TestClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from backend.app.desktop_bridge import create_desktop_app
from backend.app import mcp_desktop


class DesktopBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = self.enterContext(TestClient(create_desktop_app(Path(self.tmp.name) / 'test.sqlite3')))
        self.source = self.client.post('/api/sources', json={'title': '登录规则', 'content': '登录密码错误应提示失败。'}).json()
        self.case = {'title': '密码错误', 'preconditions': '账号存在', 'steps': ['输入错误密码'], 'expected_result': '提示失败', 'priority': 'P1'}

    def test_wiki_and_cases_share_source_and_require_manual_confirmation(self):
        source = self.source['id']
        request = {'topic': '登录', 'source_ids': [source]}
        context = self.client.post('/api/desktop/wiki-context', json=request)
        self.assertEqual(context.status_code, 200)
        chunk_id = context.json()['chunks'][0]['id']
        bad = {**request, 'title': '登录', 'sections': [{'heading': '条件', 'text': '密码错误', 'chunk_ids': [999]}]}
        self.assertEqual(self.client.post('/api/desktop/wiki-drafts', json=bad).status_code, 422)
        good = {**bad, 'sections': [{'heading': '条件', 'text': '密码错误', 'chunk_ids': [chunk_id]}]}
        wiki = self.client.post('/api/desktop/wiki-drafts', json=good)
        self.assertEqual(wiki.status_code, 201)
        self.assertEqual(self.client.post(f"/api/wiki-pages/{wiki.json()['id']}/publish").status_code, 200)
        requirement = {'requirement': '登录密码错误提示', 'source_ids': [source]}
        evidence_context = self.client.post('/api/desktop/context', json=requirement).json()
        values = {**requirement, 'context_hash': evidence_context['context_hash'], 'cases': [self.case]}
        self.assertEqual(self.client.post('/api/desktop/cases', json={**values, 'context_hash': '0' * 64}).status_code, 409)
        batch = self.client.post('/api/desktop/cases', json={**values, 'evidence': [{'text': '伪造'}]})
        self.assertEqual(batch.status_code, 201, batch.text)
        self.assertTrue(batch.json()['evidence'])
        self.assertNotIn('伪造', str(batch.json()['evidence']))
        batch_id = batch.json()['id']
        self.assertEqual(self.client.get(f'/api/case-batches/{batch_id}/export.csv').status_code, 409)
        self.assertIsNone(batch.json()['confirmed_at'])

    def test_review_snapshot_and_bad_index(self):
        request = {'requirement': '登录密码错误', 'source_ids': [self.source['id']]}
        snapshot = self.client.post('/api/desktop/context', json=request).json()
        body = {**request, 'context_hash': snapshot['context_hash'], 'cases': [self.case]}
        batch_id = self.client.post('/api/desktop/cases', json=body).json()['id']
        url = f'/api/desktop/review/{batch_id}'
        snapshot = self.client.get(url).json()
        issue = {'case_index': 1, 'description': '问题', 'suggestion': '修改'}
        self.assertEqual(self.client.post(url, json={'cases_hash': snapshot['cases_hash'], 'issues': [issue]}).status_code, 422)
        issue['case_index'] = 0
        reviewed = self.client.post(url, json={'cases_hash': snapshot['cases_hash'], 'issues': [issue]})
        self.assertEqual(reviewed.status_code, 200)
        self.assertFalse(reviewed.json()['review_stale'])
        edited = {**self.case, 'title': '已编辑'}
        self.client.put(f'/api/case-batches/{batch_id}', json={'cases': [edited], 'confirmed': True})
        self.assertEqual(self.client.post(url, json={'cases_hash': snapshot['cases_hash'], 'issues': [issue]}).status_code, 409)
        self.assertTrue(self.client.get(f'/api/case-batches/{batch_id}').json()['review_stale'])

    def test_missing_source_does_not_create_cases(self):
        response = self.client.post('/api/desktop/cases', json={'requirement': '登录密码', 'source_ids': [999], 'context_hash': '0' * 64, 'cases': [self.case]})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get('/api/case-batches').json(), [])

    def test_published_wiki_changes_context_and_rejects_old_hash(self):
        req = {'requirement': '登录密码错误', 'source_ids': [self.source['id']]}
        old = self.client.post('/api/desktop/context', json=req).json()
        wiki = {'topic': '登录', 'source_ids': [self.source['id']], 'title': '密码',
                'sections': [{'heading': '错误', 'text': '登录密码错误', 'chunk_ids': [self.source['chunks'][0]['id']]}]}
        page = self.client.post('/api/desktop/wiki-drafts', json=wiki).json()
        self.assertEqual(self.client.post(f"/api/wiki-pages/{page['id']}/publish").status_code, 200)
        response = self.client.post('/api/desktop/cases', json={**req, 'context_hash': old['context_hash'], 'cases': [self.case]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.get('/api/case-batches').json(), [])

    def test_mcp_tools_use_server_contract(self):
        with patch.object(mcp_desktop, 'request', return_value={'id': 1}) as call:
            mcp_desktop.save_test_cases('登录密码', [1], '0' * 64, [self.case])
            call.assert_called_once_with('POST', '/api/desktop/cases', {'requirement': '登录密码', 'source_ids': [1], 'context_hash': '0' * 64, 'cases': [self.case]})
        with patch.object(mcp_desktop, 'request', return_value={'id': 1}) as call:
            mcp_desktop.save_wiki_draft('登录', [1], '标题', [{'heading': 'h', 'text': 't', 'chunk_ids': [1]}])
            call.assert_called_once_with('POST', '/api/desktop/wiki-drafts', {'topic': '登录', 'source_ids': [1], 'title': '标题', 'sections': [{'heading': 'h', 'text': 't', 'chunk_ids': [1]}]})


class DesktopMcpIntegration(unittest.TestCase):
    def test_handshake_and_context(self):
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', 8000))
            except OSError:
                self.skipTest('端口 8000 被占用，不接入或停止既有服务')
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            env = os.environ.copy()
            env['KNOWLEDGE_DB_PATH'] = str(Path(directory) / 'test.sqlite3')
            process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.desktop_bridge:app', '--host', '127.0.0.1', '--port', '8000'], cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                for _ in range(80):
                    if process.poll() is not None:
                        self.fail('本次临时后端未启动')
                    try:
                        if httpx.get('http://127.0.0.1:8000/api/health', trust_env=False, timeout=0.5).status_code == 200:
                            break
                    except (httpx.ConnectError, httpx.ConnectTimeout):
                        pass
                    time.sleep(0.1)
                else:
                    self.fail('本次临时后端未响应')
                created = httpx.post('http://127.0.0.1:8000/api/sources', json={'title': '自编测试', 'content': '用户登录密码错误时提示失败'}, trust_env=False)
                self.assertEqual(created.status_code, 201)
                source_id = created.json()['id']

                async def invoke():
                    params = StdioServerParameters(command=sys.executable, args=['-m', 'backend.app.mcp_desktop'], cwd=root)
                    async with stdio_client(params) as (read, write):
                        async with ClientSession(read, write) as client:
                            await client.initialize()
                            tools = await client.list_tools()
                            self.assertTrue({'prepare_wiki', 'save_wiki_draft', 'prepare_test_cases', 'save_test_cases', 'prepare_review', 'save_review'} <= {t.name for t in tools.tools})
                            result = await client.call_tool('prepare_test_cases', {'requirement': '登录密码错误', 'source_ids': [source_id]})
                            self.assertFalse(result.isError)
                            payload = result.structuredContent or json.loads(result.content[0].text)
                            self.assertTrue(payload['evidence'])
                            self.assertEqual(payload['evidence'][0]['source_title'], '自编测试')
                asyncio.run(invoke())
            finally:
                process.terminate()
                process.wait(timeout=10)
                process.stderr.close()


if __name__ == '__main__':
    unittest.main()
