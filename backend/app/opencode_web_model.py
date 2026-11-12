"""Call the locally installed OpenCode desktop CLI for one structured response."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

from .wiki_model import ModelError


MODEL = 'opencode/deepseek-v4.1-flash-free'
POLICIES = {
    'policies': [
        {'action': action, 'resource': '*', 'effect': 'deny'}
        for action in ('mcp.use', 'plugin.use', 'skill.use', 'tool.use')
    ],
    'permissions': [{'action': '*', 'resource': '*', 'effect': 'deny'}],
}


def parse_events(stdout: str, returncode: int) -> dict:
    """Interpret OpenCode JSONL without exposing diagnostic contents to users."""
    texts = []
    events = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        events.append(event)
        if event.get('type') == 'tool_use':
            raise ModelError('模型尝试调用工具，本次结果未保存。')
        if event.get('type') == 'text' and isinstance(event.get('part'), dict):
            value = event['part'].get('text', '')
            if not isinstance(value, str):
                raise ModelError('模型未返回有效的文本结果，请重试。')
            texts.append(value)

    errors = [event for event in events if event.get('type') == 'error']
    detail = json.dumps(errors, ensure_ascii=False).lower()
    if 'provider.free-limit' in detail or '429' in detail:
        raise ModelError('当前模型额度或请求频率受限，请稍后重试。')
    if errors or returncode:
        raise ModelError('OpenCode 模型调用失败，请检查本机登录状态和网络。')

    answer = ''.join(texts).strip()
    if answer.startswith('```') and answer.endswith('```'):
        answer = answer.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    try:
        result = json.loads(answer)
    except (ValueError, TypeError) as error:
        raise ModelError('模型未返回有效的结构化结果，请重试。') from error
    if not isinstance(result, dict):
        raise ModelError('模型返回格式不完整，请重试。')
    return result


def generate_json(system: str, user: str) -> dict:
    executable = Path(os.environ.get('OPENCODE_DESKTOP_CLI', str(
        Path.home() / 'AppData/Roaming/ai.opencode.desktop/cli/2.2.6-x64/opencode-cli.exe'
    )))
    if not executable.is_file():
        raise ModelError('找不到 OpenCode 桌面程序，请检查启动说明。')
    model = os.environ.get('GRADUATION_OPENCODE_MODEL', MODEL)
    prompt = json.dumps({'instruction': system, 'input': user,
                         'output_requirement': '只返回 JSON 对象，不要调用任何工具。'}, ensure_ascii=False)
    command = [str(executable), 'run', '--standalone', '--archived', '--model', model,
               '--format', 'json', '--title', '毕设知识助手', prompt]
    # Include executable, flags and Windows escaping in the CreateProcess limit.
    if len(subprocess.list2cmdline(command).encode('utf-16-le')) // 2 > 32000:
        raise ModelError('提交的资料过长，请缩小选择范围后重试。')

    # Request tool and optional integration denial in this isolated directory.
    # Broader OpenCode policies can override project policies; credentials are
    # still resolved by OpenCode itself.
    with tempfile.TemporaryDirectory(prefix='graduation-opencode-') as directory:
        Path(directory, 'opencode.json').write_text(json.dumps(POLICIES), encoding='utf-8')
        env = os.environ.copy()
        env.pop('OPENCODE_CONFIG_CONTENT', None)
        env.pop('OPENCODE_CONFIG', None)
        try:
            result = subprocess.run(
                command,
                cwd=directory, env=env, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=240, check=False,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        except subprocess.TimeoutExpired as error:
            raise ModelError('模型响应超时，请稍后重试。') from error
        except OSError as error:
            raise ModelError('OpenCode 无法启动，请检查本机程序和权限。') from error
    return parse_events(result.stdout, result.returncode)
