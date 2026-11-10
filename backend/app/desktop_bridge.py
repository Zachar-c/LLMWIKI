"""Local endpoints for an external, user-directed AI client.

Start: python -m uvicorn backend.app.desktop_bridge:app --host 127.0.0.1 --port 8000
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .cases import CaseRequest, GeneratedCases, Review, _hash, _json, _read, retrieve
from .db import connect
from .main import create_app
from .wiki import DraftRequest, WikiContent, _chunks, _page, _validate_references


class IncomingCases(CaseRequest, GeneratedCases):
    context_hash: str = Field(min_length=64, max_length=64)


class IncomingWiki(DraftRequest, WikiContent):
    pass


class IncomingReview(Review):
    cases_hash: str = Field(min_length=64, max_length=64)


def desktop_router(path: Path) -> APIRouter:
    router = APIRouter(prefix='/api/desktop')

    @router.post('/context')
    def context(request: CaseRequest):
        if not request.requirement.strip():
            raise HTTPException(422, '请输入测试需求。')
        evidence = retrieve(path, request.requirement, request.source_ids)
        if not evidence:
            raise HTTPException(422, '所选资料未检索到相关内容。')
        return {'requirement': request.requirement, 'source_ids': list(dict.fromkeys(request.source_ids)), 'evidence': evidence, 'context_hash': _hash(_json(evidence))}

    @router.post('/cases', status_code=201)
    def save_cases(request: IncomingCases):
        result = context(CaseRequest(requirement=request.requirement, source_ids=request.source_ids))
        if request.context_hash != result['context_hash']:
            raise HTTPException(409, '参考资料或 Wiki 已变化，请重新检索后生成。')
        with connect(path) as connection:
            cursor = connection.execute(
                'INSERT INTO case_batches (requirement,cases_json,evidence_json,created_at) VALUES (?,?,?,?)',
                (request.requirement, _json([case.model_dump() for case in request.cases]), _json(result['evidence']), datetime.now(timezone.utc).isoformat(timespec='seconds')),
            )
            return _read(connection, cursor.lastrowid)

    @router.get('/review/{batch_id}')
    def review_context(batch_id: int):
        with connect(path) as connection:
            batch = _read(connection, batch_id)
        return {'id': batch_id, 'requirement': batch['requirement'], 'cases': batch['cases'], 'evidence': batch['evidence'], 'cases_hash': _hash(_json(batch['cases']))}

    @router.post('/review/{batch_id}')
    def save_review(batch_id: int, request: IncomingReview):
        with connect(path) as connection:
            batch = _read(connection, batch_id)
            current_hash = _hash(_json(batch['cases']))
            if request.cases_hash != current_hash:
                raise HTTPException(409, '用例已变更，请重新获取审查内容。')
            if any(issue.case_index >= len(batch['cases']) for issue in request.issues):
                raise HTTPException(422, '审查引用了不存在的用例。')
            review = Review(issues=request.issues)
            cursor = connection.execute('UPDATE case_batches SET review_json=?,review_hash=? WHERE id=? AND cases_json=?', (_json(review.model_dump()), current_hash, batch_id, _json(batch['cases'])))
            if cursor.rowcount != 1:
                raise HTTPException(409, '用例已变更，请重新获取审查内容。')
            return _read(connection, batch_id)

    @router.post('/wiki-context')
    def wiki_context(request: DraftRequest):
        source_ids = list(dict.fromkeys(request.source_ids))
        with connect(path) as connection:
            chunks = _chunks(connection, source_ids)
        length = sum(len(c['text']) for c in chunks)
        if not chunks or length > 12000:
            raise HTTPException(422, f'选中资料的分段合计 {length} 字符；请提供有内容的资料，且不超过 12000 字符。')
        return {'topic': request.topic, 'source_ids': source_ids, 'chunks': chunks}

    @router.post('/wiki-drafts', status_code=201)
    def save_wiki(request: IncomingWiki):
        result = wiki_context(DraftRequest(topic=request.topic, source_ids=request.source_ids))
        _validate_references(request, result['chunks'])
        with connect(path) as connection:
            cursor = connection.execute("INSERT INTO wiki_pages (title,sections_json,source_ids_json,status,created_at) VALUES (?,?,?,'draft',?)", (
                request.title, json.dumps([section.model_dump() for section in request.sections], ensure_ascii=False), json.dumps(result['source_ids']), datetime.now(timezone.utc).isoformat(timespec='seconds'),
            ))
            page = _page(connection, cursor.lastrowid)
            page['evidence'] = result['chunks']
            return page

    return router


def create_desktop_app(path: Path | None = None):
    path = path if path is not None else Path(os.environ.get('KNOWLEDGE_DB_PATH', str(Path(__file__).resolve().parents[1] / 'data' / 'knowledge.sqlite3')))
    app = create_app(path)
    app.include_router(desktop_router(path))
    return app


app = create_desktop_app()
