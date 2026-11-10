import json
import unittest

from backend.app.opencode_web_model import parse_events
from backend.app.wiki_model import ModelError


def event(kind, **kwargs):
    return json.dumps({'type': kind, **kwargs}, ensure_ascii=False)


class OpenCodeWebModelTests(unittest.TestCase):
    def test_parses_structured_text_event(self):
        lines = [event('step_start'), event('text', part={'text': '```json\n{"title":"示例"}\n```'})]
        self.assertEqual(parse_events('\n'.join(lines), 0), {'title': '示例'})

    def test_free_limit_is_explained(self):
        output = event('error', error={'type': 'provider.free-limit', 'status': 429})
        with self.assertRaisesRegex(ModelError, '额度'):
            parse_events(output, 1)

    def test_no_result_or_unexpected_tool_is_not_a_success(self):
        with self.assertRaises(ModelError):
            parse_events(event('step_start'), 0)
        with self.assertRaisesRegex(ModelError, '工具'):
            parse_events(event('tool_use'), 0)


if __name__ == '__main__':
    unittest.main()
