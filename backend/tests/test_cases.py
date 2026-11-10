import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend.app.main import create_app


class CasesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = self.enterContext(TestClient(create_app(Path(self.temp.name) / 'test.db')))
        response = self.client.post('/api/sources', json={'title': '登录规则', 'content': '账号密码登录，密码错误应提示失败。'})
        self.source_id = response.json()['id']
        self.case = {'title': '密码错误', 'preconditions': '账号存在', 'steps': ['输入账号', '输入错误密码'], 'expected_result': '提示失败', 'priority': 'P1'}

    def generate(self):
        with patch('backend.app.cases.generate_json', return_value={'cases': [self.case]}):
            response = self.client.post('/api/case-batches/generate', json={'requirement': '密码错误登录提示', 'source_ids': [self.source_id]})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_generate_review_edit_export_and_stale_review(self):
        batch = self.generate()
        self.assertEqual(self.client.get(f"/api/case-batches/{batch['id']}/export.csv").status_code, 409)
        self.assertEqual(batch['evidence'][0]['source_title'], '登录规则')
        self.assertEqual(batch['cases'][0]['title'], '密码错误')
        with patch('backend.app.cases.generate_json', return_value={'issues': [{'case_index': 0, 'description': '缺少边界', 'suggestion': '补充空密码'}]}):
            reviewed = self.client.post(f"/api/case-batches/{batch['id']}/review").json()
        self.assertFalse(reviewed['review_stale'])
        edited = dict(self.case, title='=密码错误')
        updated = self.client.put(f"/api/case-batches/{batch['id']}", json={'cases': [edited], 'confirmed': True}).json()
        self.assertTrue(updated['review_stale'])
        export = self.client.get(f"/api/case-batches/{batch['id']}/export.csv")
        self.assertEqual(export.status_code, 200)
        self.assertIn("'=密码错误", export.text)
        self.assertEqual(self.client.get(f"/api/case-batches/{batch['id']}").json()['cases'][0]['title'], '=密码错误')

    def test_no_evidence_or_invalid_model_output_never_creates_batch(self):
        with patch('backend.app.cases.generate_json') as model:
            response = self.client.post('/api/case-batches/generate', json={'requirement': '不存在的火箭燃料', 'source_ids': [self.source_id]})
            self.assertEqual(response.status_code, 422)
            model.assert_not_called()
        with patch('backend.app.cases.generate_json', return_value={'cases': [{'title': '缺少内容'}]}):
            response = self.client.post('/api/case-batches/generate', json={'requirement': '登录密码', 'source_ids': [self.source_id]})
            self.assertEqual(response.status_code, 502)
        self.assertEqual(self.client.get('/api/case-batches').json(), [])

    def test_unconfigured_model_is_visible_error(self):
        with patch.dict('os.environ', {'LLM_BASE_URL': '', 'LLM_API_KEY': '', 'LLM_MODEL': ''}):
            response = self.client.post('/api/case-batches/generate', json={'requirement': '登录密码', 'source_ids': [self.source_id]})
        self.assertEqual(response.status_code, 503)
        self.assertIn('LLM_BASE_URL', response.json()['detail'])
        self.assertEqual(self.client.get('/api/case-batches').json(), [])

    def test_published_wiki_keeps_all_original_sources(self):
        second = self.client.post('/api/sources', json={'title': '密码说明', 'version': 'v2', 'content': '密码错误后暂停登录。'}).json()
        first = self.client.get(f'/api/sources/{self.source_id}').json()
        wiki = {'title': '密码测试知识', 'sections': [{'heading': '密码', 'text': '密码错误登录需要核查提示和暂停。', 'chunk_ids': [first['chunks'][0]['id'], second['chunks'][0]['id']]}]}
        with patch('backend.app.wiki.generate_json', return_value=wiki):
            page = self.client.post('/api/wiki-drafts', json={'topic': '密码', 'source_ids': [self.source_id, second['id']]}).json()
        self.assertEqual(self.client.post(f"/api/wiki-pages/{page['id']}/publish").status_code, 200)
        with patch('backend.app.cases.generate_json', return_value={'cases': [self.case]}):
            batch = self.client.post('/api/case-batches/generate', json={'requirement': '密码错误登录', 'source_ids': [self.source_id, second['id']]}).json()
        item = next(value for value in batch['evidence'] if value['kind'] == 'Wiki')
        self.assertEqual({value['source_title'] for value in item['originals']}, {'登录规则', '密码说明'})
        self.assertEqual(len(item['originals']), 2)

    def test_blank_case_fields_are_rejected(self):
        batch = self.generate()
        invalid = dict(self.case, title='  ')
        response = self.client.put(f"/api/case-batches/{batch['id']}", json={'cases': [invalid], 'confirmed': True})
        self.assertEqual(response.status_code, 422)
        self.assertIsNone(self.client.get(f"/api/case-batches/{batch['id']}").json()['confirmed_at'])


if __name__ == '__main__':
    unittest.main()
