"""Web entry using the user's ChatGPT subscription via Codex CLI."""
from pathlib import Path

from .chatgpt_model import generate_json
from .web_opencode import create_web_app


def create_chatgpt_app(path: Path | None = None):
    return create_web_app(path, generator=generate_json)


app = create_chatgpt_app()
