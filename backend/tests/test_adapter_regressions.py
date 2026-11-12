import json
import os
import unittest
from unittest.mock import patch

from backend.app import mcp_server
from backend.app.opencode_web_model import parse_events
from backend.app.wiki_model import ModelError


class AdapterRegressionTests(unittest.TestCase):
    def test_rate_limit_message_is_model_neutral_at_source(self):
        output = json.dumps({'type': 'error', 'error': {'type': 'provider.free-limit'}})
        with self.assertRaisesRegex(ModelError, '当前模型'):
            parse_events(output, 1)

    def test_malformed_text_event_is_a_model_error(self):
        for value in (None, 123, {'unexpected': 'object'}):
            with self.subTest(value=value), self.assertRaises(ModelError):
                parse_events(json.dumps({'type': 'text', 'part': {'text': value}}), 0)

    def test_mcp_uses_configured_backend_and_waits_for_model(self):
        response = unittest.mock.Mock(is_error=False)
        response.json.return_value = []
        with patch.dict(os.environ, {'KNOWLEDGE_API_ROOT': 'http://127.0.0.1:8012/'}):
            with patch.object(mcp_server.httpx, 'Client') as factory:
                factory.return_value.__enter__.return_value.request.return_value = response
                self.assertEqual(mcp_server.request_api('GET', '/api/sources'), [])
                request = factory.return_value.__enter__.return_value.request
                self.assertEqual(request.call_args.args[1], 'http://127.0.0.1:8012/api/sources')
                self.assertGreaterEqual(factory.call_args.kwargs['timeout'], 270)


if __name__ == '__main__':
    unittest.main()
