import json
import subprocess
import unittest
from unittest.mock import patch

from backend.app.chatgpt_model import generate_json, parse_events
from backend.app.wiki_model import ModelError


def event(kind, **values):
    return json.dumps({'type': kind, **values}, ensure_ascii=False)


def success(value):
    return '\n'.join([
        event('item.completed', item={'type': 'agent_message', 'text': json.dumps(value)}),
        event('turn.completed', usage={}),
    ])


class ChatGPTModelTests(unittest.TestCase):
    def test_structured_final_response(self):
        self.assertEqual(parse_events(success({'title': '知识页'}), 0), {'title': '知识页'})

    def test_recovered_transport_error_with_completed_turn_is_success(self):
        output = event('error', message='Reconnecting... request timed out') + '\n' + success({'ok': True})
        self.assertEqual(parse_events(output, 0), {'ok': True})

    def test_incomplete_error_or_tool_run_is_rejected(self):
        outputs = [
            event('item.completed', item={'type': 'agent_message', 'text': '{}'}),
            event('turn.failed', error={'message': 'unavailable'}),
            event('item.started', item={'type': 'command_execution', 'command': 'anything'}),
            event('item.started', item={'type': 'collab_tool_call', 'tool': 'spawn_agent'}) + '\n' + success({'ok': True}),
            event('item.completed', item={'type': 'agent_message', 'text': '[]'}) + '\n' + event('turn.completed'),
        ]
        for output in outputs:
            with self.subTest(output=output), self.assertRaises(ModelError):
                parse_events(output, 0)

    def test_cli_reuses_chatgpt_login_and_receives_long_input_via_stdin(self):
        response = subprocess.CompletedProcess([], 0, stdout=success({'ok': True}), stderr='')
        with patch('backend.app.chatgpt_model.shutil.which', return_value='codex.exe'):
            with patch('backend.app.chatgpt_model.subprocess.run', return_value=response) as run:
                self.assertEqual(generate_json('仅输出 JSON', '资料' * 20000), {'ok': True})
        command = run.call_args.args[0]
        self.assertIn('gpt-6-luna', command)
        self.assertIn('forced_login_method="chatgpt"', command)
        self.assertIn('--ignore-user-config', command)
        self.assertIn('--ephemeral', command)
        self.assertIn('multi_agent', command)
        self.assertIn('资料' * 20000, run.call_args.kwargs['input'])
        self.assertNotIn('CODEX_API_KEY', run.call_args.kwargs['env'])
        self.assertNotIn('OPENAI_API_KEY', run.call_args.kwargs['env'])
        self.assertNotIn('资料', ' '.join(command))

    def test_missing_cli_and_timeout_are_model_errors(self):
        with patch('backend.app.chatgpt_model.shutil.which', return_value=None):
            with self.assertRaisesRegex(ModelError, 'Codex'):
                generate_json('规则', '资料')
        with patch('backend.app.chatgpt_model.shutil.which', return_value='codex.exe'):
            with patch('backend.app.chatgpt_model.subprocess.run', side_effect=subprocess.TimeoutExpired('codex', 240)):
                with self.assertRaisesRegex(ModelError, '超时'):
                    generate_json('规则', '资料')


if __name__ == '__main__':
    unittest.main()
