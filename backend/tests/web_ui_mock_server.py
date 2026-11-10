"""Isolated mock-only server for the browser workflow verification."""
import json
import sys
from pathlib import Path

import uvicorn
from backend.app.web_opencode import create_web_app


def fake_model(system, user):
    data = json.loads(user)
    if '整理主题知识页' in system:
        return {'title': '模拟登录知识', 'sections': [{'heading': '登录失败', 'text': '登录密码错误提示失败。', 'chunk_ids': [data['chunks'][0]['id']]}]}
    if '你是软件测试人员' in system:
        return {'cases': [{'title': '模拟密码错误', 'preconditions': '测试账号存在', 'steps': ['输入错误密码'], 'expected_result': '提示登录失败', 'priority': 'P1'}]}
    return {'issues': [{'case_index': 0, 'description': '模拟审查：补充失败边界', 'suggestion': '检查连续失败次数'}]}


if __name__ == '__main__':
    app = create_web_app(Path(sys.argv[2]), generator=fake_model)
    uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]), log_level='warning')
