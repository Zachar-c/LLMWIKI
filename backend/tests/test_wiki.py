import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.db import initialize
from backend.app.sources import SourceCreate, create_source
from backend.app.wiki import initialize_wiki, wiki_router
from backend.app.wiki_model import ModelError, generate_json


class WikiTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'wiki.sqlite3'
        initialize(self.path)
        initialize_wiki(self.path)
        self.source = create_source(self.path, SourceCreate(title='自编来源', content='登录失败时显示提示。', version='v1'))
        app = FastAPI()
        app.include_router(wiki_router(self.path))
        self.client = self.enterContext(TestClient(app))
        self.chunk_id = self.source['chunks'][0]['id']

    def response(self, chunk_id=None):
        return {'title': '登录检查', 'sections': [{'heading': '失败提示', 'text': '登录失败显示提示。', 'chunk_ids': [chunk_id if chunk_id is not None else self.chunk_id]}]}

    def test_draft_edit_publish_and_evidence(self):
        with patch('backend.app.wiki.generate_json', return_value=self.response()):
            result = self.client.post('/api/wiki-drafts', json={'source_ids': [self.source['id']], 'topic': '登录'})
        self.assertEqual(result.status_code, 201)
        page = result.json()
        self.assertEqual(page['status'], 'draft')
        self.assertEqual(page['evidence'][0]['text'], '登录失败时显示提示。')
        content = self.response()
        content['sections'][0]['text'] = '人工核对后的内容。'
        result = self.client.put(f"/api/wiki-pages/{page['id']}", json=content)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['sections'][0]['text'], '人工核对后的内容。')
        self.assertEqual(self.client.post(f"/api/wiki-pages/{page['id']}/publish").json()['status'], 'published')
        self.assertEqual(self.client.put(f"/api/wiki-pages/{page['id']}", json=content).status_code, 409)
        self.assertEqual(self.client.get('/api/wiki-pages').json()[0]['status'], 'published')

    def test_bad_reference_or_failed_model_creates_no_page(self):
        with patch('backend.app.wiki.generate_json', return_value=self.response(999)):
            self.assertEqual(self.client.post('/api/wiki-drafts', json={'source_ids': [self.source['id']], 'topic': '登录'}).status_code, 422)
        with patch('backend.app.wiki.generate_json', side_effect=ModelError('未配置')):
            self.assertEqual(self.client.post('/api/wiki-drafts', json={'source_ids': [self.source['id']], 'topic': '登录'}).status_code, 503)
        self.assertEqual(self.client.get('/api/wiki-pages').json(), [])

    def test_scope_and_input_limit_checked_before_model(self):
        source = create_source(self.path, SourceCreate(title='长资料', content='字' * 12000))
        with patch('backend.app.wiki.generate_json') as call:
            result = self.client.post('/api/wiki-drafts', json={'source_ids': [source['id']], 'topic': '主题'})
            self.assertEqual(result.status_code, 422)
            self.assertIn('12000', result.json()['detail'])
            self.assertEqual(self.client.post('/api/wiki-drafts', json={'source_ids': [999], 'topic': '主题'}).status_code, 422)
            call.assert_not_called()

    def test_edit_cannot_reference_another_source(self):
        other = create_source(self.path, SourceCreate(title='另一个来源', content='无关内容'))
        with patch('backend.app.wiki.generate_json', return_value=self.response()):
            page = self.client.post('/api/wiki-drafts', json={'source_ids': [self.source['id']], 'topic': '登录'}).json()
        result = self.client.put(f"/api/wiki-pages/{page['id']}", json=self.response(other['chunks'][0]['id']))
        self.assertEqual(result.status_code, 422)
        self.assertEqual(self.client.get(f"/api/wiki-pages/{page['id']}").json()['sections'][0]['chunk_ids'], [self.chunk_id])


class ModelTests(unittest.TestCase):
    def test_missing_configuration_and_model_http_shape(self):
        with patch.dict(os.environ, {'LLM_BASE_URL': '', 'LLM_API_KEY': '', 'LLM_MODEL': ''}):
            with self.assertRaises(ModelError):
                generate_json('规则', '内容')
        fake_response = httpx.Response(200, json={'choices': [{'message': {'content': '{"answer":"ok"}'}}]}, request=httpx.Request('POST', 'https://example.test/v1/chat/completions'))
        with patch.dict(os.environ, {'LLM_BASE_URL': 'https://example.test/v1', 'LLM_API_KEY': 'test-key', 'LLM_MODEL': 'test-model'}), patch('backend.app.wiki_model.httpx.post', return_value=fake_response) as post:
            self.assertEqual(generate_json('规则', '内容'), {'answer': 'ok'})
            self.assertEqual(post.call_args.args[0], 'https://example.test/v1/chat/completions')
            self.assertEqual(post.call_args.kwargs['json']['messages'][1]['content'], '内容')


if __name__ == '__main__':
    unittest.main()
