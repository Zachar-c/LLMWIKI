"""Local OpenCode adapter. External plugins, MCP and agent tools are disabled."""
import json
import os
import subprocess
import tempfile

from .wiki_model import ModelError


_ENCODING = '[Console]::InputEncoding=[System.Text.UTF8Encoding]::new($false); [Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); $OutputEncoding=[System.Text.UTF8Encoding]::new($false); '
_DEBUG = _ENCODING + '& opencode debug config --pure'
_RUN = _ENCODING + '$message=[Console]::In.ReadToEnd(); $message | & opencode run --pure --format json --agent bishe_guarded --model $env:GRAD_ASSISTANT_MODEL --title "毕业设计生成"'


def _execute(script: str, env: dict, directory: str, *, message: str = '', timeout: int = 45):
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
            input=message, capture_output=True, text=True, encoding='utf-8', errors='replace',
            cwd=directory, env=env, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ModelError('OpenCode 无法启动或请求超时，请检查本机程序和网络。') from error
    if result.returncode:
        raise ModelError('OpenCode 调用失败，请检查模型是否可用和本机登录状态。')
    return result.stdout


def _config(env: dict, directory: str) -> dict:
    try:
        config = json.loads(_execute(_DEBUG, env, directory))
    except (ValueError, TypeError) as error:
        raise ModelError('无法核验 OpenCode 配置，已停止调用。') from error
    if not isinstance(config, dict):
        raise ModelError('OpenCode 配置格式异常，已停止调用。')
    return config


def generate_json(system: str, user: str) -> dict:
    """Use the specified OpenCode model without enabling configured tools or MCPs."""
    env = os.environ.copy()
    env['GRAD_ASSISTANT_MODEL'] = env.get('OPENCODE_MODEL', 'opencode/mimo-v2.6-flash-free').strip()
    if not env['GRAD_ASSISTANT_MODEL']:
        raise ModelError('请设置 OpenCode 模型名称。')
    with tempfile.TemporaryDirectory(prefix='bishe-opencode-') as directory:
        before = _config(env, directory)
        original_inline = env.get('OPENCODE_CONFIG_CONTENT', '')
        try:
            override = json.loads(original_inline) if original_inline else {}
            if not isinstance(override, dict):
                raise ValueError('invalid inline configuration')
        except (ValueError, TypeError) as error:
            raise ModelError('无法核验现有 OpenCode 配置，已停止调用。') from error
        override['mcp'] = {name: {'enabled': False} for name in before.get('mcp', {})}
        override['permission'] = {'*': 'deny'}
        override['agent'] = {'bishe_guarded': {'mode': 'primary', 'permission': {'*': 'deny'}}}
        env['OPENCODE_CONFIG_CONTENT'] = json.dumps(override, ensure_ascii=False)
        after = _config(env, directory)
        mcp = after.get('mcp', {})
        agent = after.get('agent', {}).get('bishe_guarded', {})
        if (not isinstance(mcp, dict) or any(not isinstance(value, dict) or value.get('enabled') is not False for value in mcp.values())
                or after.get('permission') != {'*': 'deny'} or agent.get('mode') != 'primary'
                or agent.get('permission') != {'*': 'deny'}):
            raise ModelError('OpenCode 安全配置未生效，已停止调用。')
        prompt = json.dumps({'instruction': system, 'input': user, 'output_requirement': '只输出 JSON 对象，不调用工具。'}, ensure_ascii=False)
        output = _execute(_RUN, env, directory, message=prompt, timeout=180)
    texts = []
    try:
        for line in output.splitlines():
            event = json.loads(line)
            if event.get('type') == 'error':
                raise ModelError('OpenCode 模型请求失败，请确认模型权限与登录状态。')
            if event.get('type') == 'tool_use':
                raise ModelError('OpenCode 尝试调用工具，已拒绝结果。')
            if event.get('type') == 'text':
                texts.append(event['part']['text'])
        text = ''.join(texts).strip()
        if text.startswith('```') and text.endswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        result = json.loads(text)
    except (ValueError, TypeError, KeyError, IndexError) as error:
        raise ModelError('OpenCode 未返回有效 JSON 对象，请重试。') from error
    if not isinstance(result, dict):
        raise ModelError('OpenCode 返回内容须为 JSON 对象。')
    return result
