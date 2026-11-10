import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.web_opencode_fixed import create_fixed_app
from backend.app.wiki_model import ModelError


class ModelMessageFixTests(unittest.TestCase):
    def test_rate_limit_is_not_labeled_as_a_specific_model(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_fixed_app(Path(directory) / 'test.sqlite3')
            with TestClient(app) as client:
                source = client.post('/api/sources', json={
                    'title': '自编示例', 'content': '登录时账号密码必填。',
                }).json()
                with patch('backend.app.web_opencode_fixed.original.generate_json',
                           side_effect=ModelError('DeepSeek 免费模型暂时达到使用额度，请稍后重试。')):
                    response = client.post('/api/wiki-drafts', json={
                        'topic': '登录', 'source_ids': [source['id']],
                    })
                    cases = client.post('/api/case-batches/generate', json={
                        'requirement': '登录账号密码', 'source_ids': [source['id']],
                    })
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()['detail'], '当前模型额度或请求频率受限，请稍后重试。')
                self.assertEqual(cases.status_code, 503)
                self.assertEqual(cases.json()['detail'], '当前模型额度或请求频率受限，请稍后重试。')
                self.assertEqual(client.get('/api/wiki-pages').json(), [])
                self.assertEqual(client.get('/api/case-batches').json(), [])

    def test_other_model_errors_are_preserved(self):
        from backend.app.web_opencode_fixed import generate_json
        with patch('backend.app.web_opencode_fixed.original.generate_json',
                   side_effect=ModelError('模型响应超时，请稍后重试。')):
            with self.assertRaisesRegex(ModelError, '超时'):
                generate_json('规则', '自编资料')

    def test_success_result_is_unchanged(self):
        from backend.app.web_opencode_fixed import generate_json
        with patch('backend.app.web_opencode_fixed.original.generate_json', return_value={'ok': True}):
            self.assertEqual(generate_json('规则', '自编资料'), {'ok': True})


if __name__ == '__main__':
    unittest.main()
