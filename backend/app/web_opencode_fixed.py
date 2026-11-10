"""Web entry with a model-neutral rate-limit message."""
from pathlib import Path

from . import opencode_web_model as original
from .web_opencode import create_web_app
from .wiki_model import ModelError


def generate_json(system: str, user: str) -> dict:
    try:
        return original.generate_json(system, user)
    except ModelError as error:
        if str(error) == 'DeepSeek 免费模型暂时达到使用额度，请稍后重试。':
            raise ModelError('当前模型额度或请求频率受限，请稍后重试。') from error
        raise


def create_fixed_app(path: Path | None = None):
    return create_web_app(path, generator=generate_json)


app = create_fixed_app()
