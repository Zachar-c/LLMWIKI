import json
import os

import httpx


class ModelError(Exception):
    pass


def generate_json(system: str, user: str) -> dict:
    base = os.environ.get("LLM_BASE_URL", "").strip().rstrip("/")
    key = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()
    if not all((base, key, model)):
        raise ModelError("请先在后端配置 LLM_BASE_URL、LLM_API_KEY 和 LLM_MODEL。")
    try:
        response = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "response_format": {"type": "json_object"}, "temperature": 0},
            timeout=60,
        )
        response.raise_for_status()
        result = json.loads(response.json()["choices"][0]["message"]["content"])
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
        raise ModelError("模型调用失败或未返回有效 JSON，请检查模型配置和服务状态。") from error
    if not isinstance(result, dict):
        raise ModelError("模型返回的 JSON 须为对象。")
    return result
