"""Acceptance regressions using isolated SQLite files and simulated model output."""

import hashlib
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.db import connect
from backend.app.desktop_bridge import create_desktop_app
from backend.app.main import create_app


class AcceptanceRegressionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='acceptance-regressions-')
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'isolated.sqlite3'
        self.client = self.enterContext(TestClient(create_app(self.path)))
        response = self.client.post('/api/sources', json={
            'title': '自编密码登录规则',
            'version': 'acceptance-v1',
            'content': '账号密码登录时，密码错误应显示失败提示。',
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.source = response.json()
        self.case = {
            'title': '密码错误提示',
            'preconditions': '测试账号存在',
            'steps': ['输入账号与错误密码', '提交登录'],
            'expected_result': '显示失败提示',
            'priority': 'P1',
        }

    def generate_batch(self, requirement='密码错误登录'):
        with patch('backend.app.cases.generate_json', return_value={'cases': [self.case]}) as model:
            response = self.client.post('/api/case-batches/generate', json={
                'requirement': requirement,
                'source_ids': [self.source['id']],
            })
        self.assertEqual(response.status_code, 201, response.text)
        model.assert_called_once()
        return response.json()

    def content_hash(self, response, content):
        # Keep exercising conflict handling on the baseline that lacks this field.
        serialized = json.dumps(content, ensure_ascii=False, separators=(',', ':'))
        expected_hash = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
        with self.subTest(contract='content_hash'):
            self.assertEqual(response.get('content_hash'), expected_hash)
        return response.get('content_hash', expected_hash)

    def test_case_save_rejects_stale_snapshot_and_allows_refreshed_save(self):
        batch = self.generate_batch()
        endpoint = f"/api/case-batches/{batch['id']}"
        first = self.client.get(endpoint).json()
        second = self.client.get(endpoint).json()
        first_hash = self.content_hash(first, first['cases'])
        second_hash = self.content_hash(second, second['cases'])

        first['cases'][0]['title'] = 'A 已确认的标题'
        saved = self.client.put(endpoint, json={
            'cases': first['cases'], 'confirmed': True, 'base_hash': first_hash,
        })
        self.assertEqual(saved.status_code, 200, saved.text)

        second['cases'][0]['expected_result'] = 'B 补充的预期'
        conflicting = self.client.put(endpoint, json={
            'cases': second['cases'], 'confirmed': True, 'base_hash': second_hash,
        })
        after_conflict = self.client.get(endpoint).json()
        with self.subTest(operation='reject_stale_save'):
            self.assertEqual(conflicting.status_code, 409, conflicting.text)
        with self.subTest(operation='preserve_confirmed_edit'):
            self.assertEqual(after_conflict['cases'][0]['title'], 'A 已确认的标题')

        current_hash = self.content_hash(after_conflict, after_conflict['cases'])
        after_conflict['cases'][0]['expected_result'] = 'B 刷新后补充的预期'
        refreshed = self.client.put(endpoint, json={
            'cases': after_conflict['cases'], 'confirmed': True, 'base_hash': current_hash,
        })
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertEqual(refreshed.json()['cases'][0]['expected_result'], 'B 刷新后补充的预期')

    def test_wiki_save_rejects_stale_snapshot_and_allows_refreshed_save(self):
        content = {
            'title': '密码登录知识',
            'sections': [{
                'heading': '失败提示', 'text': '密码错误显示失败提示。',
                'chunk_ids': [self.source['chunks'][0]['id']],
            }],
        }
        with patch('backend.app.wiki.generate_json', return_value=content):
            created = self.client.post('/api/wiki-drafts', json={
                'topic': '密码登录', 'source_ids': [self.source['id']],
            })
        self.assertEqual(created.status_code, 201, created.text)
        endpoint = f"/api/wiki-pages/{created.json()['id']}"
        first = self.client.get(endpoint).json()
        second = self.client.get(endpoint).json()
        first_content = {'title': first['title'], 'sections': first['sections']}
        second_content = {'title': second['title'], 'sections': second['sections']}
        first_hash = self.content_hash(first, first_content)
        second_hash = self.content_hash(second, second_content)

        first_content['title'] = 'A 已核对的知识标题'
        saved = self.client.put(endpoint, json={**first_content, 'base_hash': first_hash})
        self.assertEqual(saved.status_code, 200, saved.text)
        second_content['sections'][0]['text'] = 'B 补充的知识正文。'
        conflicting = self.client.put(endpoint, json={**second_content, 'base_hash': second_hash})
        after_conflict = self.client.get(endpoint).json()
        with self.subTest(operation='reject_stale_save'):
            self.assertEqual(conflicting.status_code, 409, conflicting.text)
        with self.subTest(operation='preserve_confirmed_edit'):
            self.assertEqual(after_conflict['title'], 'A 已核对的知识标题')

        current_content = {'title': after_conflict['title'], 'sections': after_conflict['sections']}
        current_hash = self.content_hash(after_conflict, current_content)
        current_content['sections'][0]['text'] = 'B 刷新后补充的知识正文。'
        refreshed = self.client.put(endpoint, json={**current_content, 'base_hash': current_hash})
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertEqual(refreshed.json()['sections'][0]['text'], 'B 刷新后补充的知识正文。')

    def test_review_is_current_for_semantically_identical_legacy_json(self):
        batch = self.generate_batch()
        with connect(self.path) as connection:
            connection.execute('UPDATE case_batches SET cases_json=? WHERE id=?', (
                json.dumps(batch['cases'], ensure_ascii=False), batch['id'],
            ))
        endpoint = f"/api/case-batches/{batch['id']}"
        with patch('backend.app.cases.generate_json', return_value={'issues': []}):
            reviewed = self.client.post(endpoint + '/review')
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertFalse(reviewed.json()['review_stale'])
        reopened = self.client.get(endpoint)
        self.assertEqual(reopened.status_code, 200, reopened.text)
        self.assertFalse(reopened.json()['review_stale'])

    def test_wiki_publish_rejects_stale_snapshot_and_allows_refreshed_publish(self):
        content = {
            'title': '发布前的密码知识',
            'sections': [{
                'heading': '失败提示', 'text': '密码错误显示失败提示。',
                'chunk_ids': [self.source['chunks'][0]['id']],
            }],
        }
        with patch('backend.app.wiki.generate_json', return_value=content):
            created = self.client.post('/api/wiki-drafts', json={
                'topic': '密码登录', 'source_ids': [self.source['id']],
            })
        self.assertEqual(created.status_code, 201, created.text)
        endpoint = f"/api/wiki-pages/{created.json()['id']}"
        original = self.client.get(endpoint).json()
        revised = {**content, 'title': '另一页面修改的知识标题'}
        edited = self.client.put(endpoint, json={**revised, 'base_hash': original['content_hash']})
        self.assertEqual(edited.status_code, 200, edited.text)

        stale_publish = self.client.post(endpoint + '/publish', json={
            'base_hash': original['content_hash'],
        })
        self.assertEqual(stale_publish.status_code, 409, stale_publish.text)
        current = self.client.get(endpoint).json()
        self.assertEqual(current['status'], 'draft')
        self.assertEqual(current['title'], revised['title'])
        published = self.client.post(endpoint + '/publish', json={
            'base_hash': current['content_hash'],
        })
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(published.json()['status'], 'published')
        self.assertEqual(published.json()['title'], revised['title'])

    def test_slow_old_review_cannot_overwrite_review_of_updated_cases(self):
        batch = self.generate_batch()
        endpoint = f"/api/case-batches/{batch['id']}"
        old_review_started = threading.Event()
        release_old_review = threading.Event()
        old_issue = {'case_index': 0, 'description': '旧快照审查', 'suggestion': '旧建议'}
        current_issue = {'case_index': 0, 'description': '最新快照审查', 'suggestion': '最新建议'}

        def review_model(system, user):
            content = json.loads(user)
            if content['cases'][0]['title'] == self.case['title']:
                old_review_started.set()
                if not release_old_review.wait(timeout=10):
                    raise RuntimeError('测试未释放旧审查请求')
                return {'issues': [old_issue]}
            return {'issues': [current_issue]}

        with patch('backend.app.cases.generate_json', side_effect=review_model):
            with ThreadPoolExecutor(max_workers=1) as executor:
                old_request = executor.submit(self.client.post, endpoint + '/review')
                try:
                    self.assertTrue(old_review_started.wait(timeout=10))
                    revised = dict(self.case, title='修改后的密码错误提示')
                    saved = self.client.put(endpoint, json={
                        'cases': [revised], 'confirmed': True,
                        'base_hash': batch['content_hash'],
                    })
                    self.assertEqual(saved.status_code, 200, saved.text)
                    current_review = self.client.post(endpoint + '/review')
                    self.assertEqual(current_review.status_code, 200, current_review.text)
                    self.assertFalse(current_review.json()['review_stale'])
                finally:
                    release_old_review.set()
                old_response = old_request.result(timeout=10)
        self.assertEqual(old_response.status_code, 409, old_response.text)
        stored = self.client.get(endpoint).json()
        self.assertEqual(stored['review'], {'issues': [current_issue]})
        self.assertFalse(stored['review_stale'])

    def test_desktop_review_accepts_legacy_json_with_whitespace(self):
        batch = self.generate_batch()
        with connect(self.path) as connection:
            connection.execute('UPDATE case_batches SET cases_json=? WHERE id=?', (
                json.dumps(batch['cases']), batch['id'],
            ))
        desktop = self.enterContext(TestClient(create_desktop_app(self.path)))
        endpoint = f"/api/desktop/review/{batch['id']}"
        snapshot = desktop.get(endpoint)
        self.assertEqual(snapshot.status_code, 200, snapshot.text)
        issue = {'case_index': 0, 'description': '缺少空密码检查', 'suggestion': '补充空密码用例'}
        reviewed = desktop.post(endpoint, json={
            'cases_hash': snapshot.json()['cases_hash'], 'issues': [issue],
        })
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()['review'], {'issues': [issue]})
        self.assertFalse(reviewed.json()['review_stale'])
        stored = self.client.get(f"/api/case-batches/{batch['id']}").json()
        self.assertEqual(stored['review'], {'issues': [issue]})
        self.assertFalse(stored['review_stale'])

    def test_single_chinese_character_retrieves_long_chinese_source(self):
        batch = self.generate_batch(requirement='密')
        self.assertTrue(batch['evidence'])
        self.assertEqual(batch['evidence'][0]['source_id'], self.source['id'])

    def test_blank_review_issue_fields_are_rejected_without_saving(self):
        for field in ('description', 'suggestion'):
            with self.subTest(field=field):
                batch = self.generate_batch()
                issue = {'case_index': 0, 'description': '缺少边界', 'suggestion': '补充空密码'}
                issue[field] = ' \n\t '
                endpoint = f"/api/case-batches/{batch['id']}"
                with patch('backend.app.cases.generate_json', return_value={'issues': [issue]}):
                    response = self.client.post(endpoint + '/review')
                stored = self.client.get(endpoint).json()
                self.assertEqual((response.status_code, stored['review']), (502, None))


if __name__ == '__main__':
    unittest.main()
