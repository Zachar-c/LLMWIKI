"""Explicit alternate server entry; normal OpenAI-compatible entry is unchanged."""
from . import cases, wiki
from .opencode_model import generate_json

cases.generate_json = generate_json
wiki.generate_json = generate_json

from .main import app  # noqa: E402
