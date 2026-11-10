import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path as PathParam

from .db import initialize
from .sources import SourceCreate, create_source, get_source, list_sources
from .wiki import initialize_wiki, wiki_router
from .cases import initialize_cases, cases_router


def create_app(db_path: Path | None = None) -> FastAPI:
    path = db_path if db_path is not None else Path(os.environ.get(
        "KNOWLEDGE_DB_PATH", str(Path(__file__).resolve().parents[1] / "data" / "knowledge.sqlite3")
    ))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        initialize(path)
        initialize_wiki(path)
        initialize_cases(path)
        yield

    app = FastAPI(title="软件测试知识库", version="0.1.0", lifespan=lifespan)
    app.include_router(wiki_router(path))
    app.include_router(cases_router(path))

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/sources")
    def sources():
        return list_sources(path)

    @app.post("/api/sources", status_code=201)
    def import_source(source: SourceCreate):
        return create_source(path, source)

    @app.get("/api/sources/{source_id}")
    def source_detail(source_id: Annotated[int, PathParam(gt=0)]):
        source = get_source(path, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="资料不存在")
        return source

    return app


app = create_app()
