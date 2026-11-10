"""Alternate local entry that connects existing web routes to OpenCode v2."""
from contextvars import ContextVar
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from . import cases, wiki
from .main import create_app
from .opencode_web_model import generate_json

_request_generator = ContextVar('graduation_request_generator', default=None)
_cases_original = cases.generate_json
_wiki_original = wiki.generate_json


def _case_generator(system, user):
    return (_request_generator.get() or _cases_original)(system, user)


def _wiki_generator(system, user):
    return (_request_generator.get() or _wiki_original)(system, user)


# Preserve the original behavior for requests belonging to other application
# instances, while each request to this entry uses its own configured model.
cases.generate_json = _case_generator
wiki.generate_json = _wiki_generator


def create_web_app(path: Path | None = None, *, generator=generate_json):
    app = create_app(path)

    @app.middleware('http')
    async def bind_generator(request, call_next):
        token = _request_generator.set(generator)
        try:
            return await call_next(request)
        finally:
            _request_generator.reset(token)

    frontend = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
    if frontend.is_dir():
        app.mount('/', StaticFiles(directory=frontend, html=True), name='frontend')
    return app


app = create_web_app()
