"""API integration for the web/OpenCode entry; model responses here are simulated."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.web_opencode import create_web_app
from backend.app import cases, wiki
from backend.app.wiki_model import ModelError


class WebOpenCodeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(cases, 'generate_json', cases.generate_json))
        self.enterContext(patch.object(wiki, 'generate_json', wiki.generate_json))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.calls = []
        self.client = self.enterContext(TestClient(create_web_app(
            Path(self.temp.name) / 'isolated.sqlite3', generator=self.model
        )))
        response = self.client.post('/api/sources', json={
            'title': '自编登录规则', 'version': 'demo-v1',
            'content': '账号密码登录，密码错误时提示失败。连续失败五次暂停登录十分钟。',
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.source = response.json()

    def model(self, system, user):
        data = json.loads(user)
        if '整理主题知识页' in system:
            self.calls.append(('wiki', data))
            return {'title': '登录知识', 'sections': [{
                'heading': '失败提示', 'text': '登录密码错误应提示失败。',
                'chunk_ids': [data['chunks'][0]['id']],
            }]}
        if '你是软件测试人员' in system:
            self.calls.append(('generate', data))
            return {'cases': [{
                'title': '密码错误', 'preconditions': '测试账号存在',
                'steps': ['输入账号', '输入错误密码并提交'],
                'expected_result': '提示失败', 'priority': 'P1',
            }]}
        self.calls.append(('review', data))
        return {'issues': [{'case_index': 0, 'description': '遗漏连续失败边界', 'suggestion': '增加失败五次的检查'}]}

    def test_wiki_to_case_review_confirmation_and_export(self):
        page = self.client.post('/api/wiki-drafts', json={
            'topic': '登录密码', 'source_ids': [self.source['id']],
        })
        self.assertEqual(page.status_code, 201, page.text)
        self.assertEqual(page.json()['status'], 'draft')
        self.assertEqual(page.json()['sections'][0]['chunk_ids'], [self.source['chunks'][0]['id']])
        page_id = page.json()['id']
        published = self.client.post(f'/api/wiki-pages/{page_id}/publish')
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(published.json()['status'], 'published')

        created = self.client.post('/api/case-batches/generate', json={
            'requirement': '登录密码错误测试', 'source_ids': [self.source['id']],
        })
        self.assertEqual(created.status_code, 201, created.text)
        batch = created.json()
        self.assertTrue(any(item['kind'] == 'Wiki' for item in batch['evidence']))
        self.assertEqual([name for name, _ in self.calls], ['wiki', 'generate'])
        batch_id = batch['id']
        self.assertEqual(self.client.get(f'/api/case-batches/{batch_id}/export.csv').status_code, 409)

        review = self.client.post(f'/api/case-batches/{batch_id}/review')
        self.assertEqual(review.status_code, 200, review.text)
        self.assertFalse(review.json()['review_stale'])
        self.assertEqual(len(review.json()['review']['issues']), 1)
        self.assertEqual([name for name, _ in self.calls], ['wiki', 'generate', 'review'])
        self.assertEqual(self.calls[-1][1]['cases'][0]['title'], '密码错误')

        edited = [dict(batch['cases'][0], title='=人工确认密码错误')]
        saved = self.client.put(f'/api/case-batches/{batch_id}', json={'cases': edited, 'confirmed': True})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertIsNotNone(saved.json()['confirmed_at'])
        self.assertTrue(saved.json()['review_stale'])
        exported = self.client.get(f'/api/case-batches/{batch_id}/export.csv')
        self.assertEqual(exported.status_code, 200)
        self.assertIn("'=人工确认密码错误", exported.text)

    def test_generator_failure_does_not_create_wiki_or_cases(self):
        def failure(system, user):
            raise ModelError('模拟模型不可用')

        client = self.enterContext(TestClient(create_web_app(
            Path(self.temp.name) / 'failure.sqlite3', generator=failure
        )))
        independent = self.client.post('/api/wiki-drafts', json={
            'topic': '登录密码', 'source_ids': [self.source['id']],
        })
        self.assertEqual(independent.status_code, 201, independent.text)
        self.assertEqual([name for name, _ in self.calls], ['wiki'])
        source = client.post('/api/sources', json={
            'title': '自编资料', 'content': '登录密码错误提示失败。',
        }).json()
        wiki = client.post('/api/wiki-drafts', json={'topic': '登录', 'source_ids': [source['id']]})
        self.assertEqual(wiki.status_code, 503, wiki.text)
        self.assertIn('模拟模型不可用', wiki.json()['detail'])
        cases = client.post('/api/case-batches/generate', json={
            'requirement': '登录密码错误', 'source_ids': [source['id']],
        })
        self.assertEqual(cases.status_code, 503, cases.text)
        self.assertEqual(client.get('/api/wiki-pages').json(), [])
        self.assertEqual(client.get('/api/case-batches').json(), [])


if __name__ == '__main__':
    unittest.main()
