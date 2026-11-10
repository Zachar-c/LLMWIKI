import json
import unittest
from unittest.mock import patch

from backend.app.opencode_model import generate_json
from backend.app.wiki_model import ModelError


class OpencodeAdapterTests(unittest.TestCase):
    def test_disables_mcp_and_sends_prompt_over_stdin(self):
        calls = []
        def fake(script, env, directory, **kwargs):
            calls.append((script, dict(env), directory, kwargs))
            if len(calls) == 1:
                return json.dumps({'mcp': {'existing': {'enabled': True}}})
            if len(calls) == 2:
                return json.dumps({'mcp': {'existing': {'enabled': False}}, 'permission': {'*': 'deny'}, 'agent': {'bishe_guarded': {'mode': 'primary', 'permission': {'*': 'deny'}}}})
            return json.dumps({'type': 'text', 'part': {'text': '{"ok":true}'}})
        with patch('backend.app.opencode_model._execute', side_effect=fake):
            result = generate_json('规则', '自编资料')
        self.assertEqual(result, {'ok': True})
        self.assertEqual(len(calls), 3)
        override = json.loads(calls[1][1]['OPENCODE_CONFIG_CONTENT'])
        self.assertFalse(override['mcp']['existing']['enabled'])
        self.assertEqual(override['agent']['bishe_guarded']['permission'], {'*': 'deny'})
        self.assertIn('自编资料', calls[2][3]['message'])
        self.assertNotIn('自编资料', calls[2][0])
        self.assertEqual(calls[0][2], calls[2][2])

    def test_failed_isolation_never_calls_model(self):
        responses = [json.dumps({'mcp': {'existing': {'enabled': True}}}), json.dumps({'mcp': {'existing': {'enabled': True}}, 'permission': {'*': 'deny'}, 'agent': {}})]
        with patch('backend.app.opencode_model._execute', side_effect=responses) as run:
            with self.assertRaisesRegex(ModelError, '安全配置'):
                generate_json('规则', '资料')
        self.assertEqual(run.call_count, 2)

    def test_rejects_tool_events(self):
        safe = {'mcp': {}, 'permission': {'*': 'deny'}, 'agent': {'bishe_guarded': {'mode': 'primary', 'permission': {'*': 'deny'}}}}
        with patch('backend.app.opencode_model._execute', side_effect=[json.dumps({'mcp': {}}), json.dumps(safe), json.dumps({'type': 'tool_use'})]):
            with self.assertRaisesRegex(ModelError, '工具'):
                generate_json('规则', '资料')


if __name__ == '__main__':
    unittest.main()
