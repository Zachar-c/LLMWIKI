import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.db import connect, initialize
from backend.app.main import create_app
from backend.app.sources import SourceCreate, create_source, get_source, list_sources, split_text


class ChunkTests(unittest.TestCase):
    def test_offsets_preserve_unicode_and_cover_nonblank_content(self):
        text = " \n" + "登录😀测试\n" * 420 + "结尾\n "
        chunks = split_text(text)
        covered = set()
        for ordinal, chunk in enumerate(chunks, start=1):
            self.assertEqual(chunk["ordinal"], ordinal)
            self.assertEqual(chunk["text"], text[chunk["start_offset"]:chunk["end_offset"]])
            self.assertLessEqual(len(chunk["text"]), 800)
            covered.update(range(chunk["start_offset"], chunk["end_offset"]))
        self.assertTrue(all(i in covered for i, char in enumerate(text) if not char.isspace()))
        self.assertEqual(chunks[-1]["end_offset"], len(text))

    def test_exact_boundary_and_overlap(self):
        self.assertEqual(len(split_text("a" * 800)), 1)
        chunks = split_text("a" * 801)
        self.assertEqual([(c["start_offset"], c["end_offset"]) for c in chunks], [(0, 800), (700, 801)])
        self.assertEqual(split_text(" \n\t"), [])


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test.sqlite3"
        initialize(self.path)

    def test_reopen_preserves_text_and_metadata(self):
        text = " \n内容😀\r\n "
        created = create_source(self.path, SourceCreate(title="  示例  ", content=text, origin="自编", version="v1"))
        initialize(self.path)
        loaded = get_source(self.path, created["id"])
        self.assertEqual(loaded["content"], text)
        self.assertEqual(loaded["title"], "示例")
        self.assertEqual(loaded["sha256"], hashlib.sha256(text.encode("utf-8")).hexdigest())
        self.assertEqual(loaded["char_count"], len(text))
        self.assertEqual(loaded["chunks"][0]["text"], text)
        self.assertNotIn("content", list_sources(self.path)[0])

    def test_same_content_is_not_overwritten_or_deduplicated(self):
        first = create_source(self.path, SourceCreate(title="资料", content="原文", version="v1"))
        second = create_source(self.path, SourceCreate(title="资料", content="原文", version="v2"))
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual([s["version"] for s in list_sources(self.path)], ["v2", "v1"])
        self.assertEqual(get_source(self.path, first["id"])["version"], "v1")

    def test_chunk_failure_rolls_back_source_and_all_chunks(self):
        with connect(self.path) as connection:
            connection.execute("""
                CREATE TRIGGER reject_second_chunk BEFORE INSERT ON chunks
                WHEN NEW.ordinal = 2
                BEGIN SELECT RAISE(ABORT, 'simulated storage failure'); END
            """)
        with self.assertRaises(sqlite3.IntegrityError):
            create_source(self.path, SourceCreate(title="事务检查", content="测试" * 600))
        self.assertEqual(list_sources(self.path), [])
        with connect(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0], 0)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "api.sqlite3"
        self.client = self.enterContext(TestClient(create_app(self.path)))

    def test_create_list_and_detail_over_http(self):
        self.assertEqual(self.client.get("/api/health").json(), {"status": "ok"})
        self.assertEqual(self.client.get("/api/sources").json(), [])
        payload = {"title": "接口验证", "origin": "自编演示", "version": "v1", "content": " \n测试😀\n "}
        response = self.client.post("/api/sources", json=payload)
        self.assertEqual(response.status_code, 201)
        source = response.json()
        self.assertEqual(source["content"], payload["content"])
        detail = self.client.get(f"/api/sources/{source['id']}")
        self.assertEqual(detail.json(), source)
        listing = self.client.get("/api/sources").json()
        self.assertEqual(listing[0]["chunk_count"], 1)
        self.assertNotIn("content", listing[0])

    def test_invalid_input_does_not_write(self):
        for payload in [
            {"title": "有效标题", "content": " \n "},
            {"title": " ", "content": "正文"},
            {"title": "有效标题", "content": "字" * 100001},
        ]:
            with self.subTest(payload_title=payload["title"]):
                self.assertEqual(self.client.post("/api/sources", json=payload).status_code, 422)
        self.assertEqual(self.client.get("/api/sources").json(), [])

    def test_missing_and_invalid_id(self):
        self.assertEqual(self.client.get("/api/sources/999").status_code, 404)
        self.assertEqual(self.client.get("/api/sources/0").status_code, 422)


if __name__ == "__main__":
    unittest.main()
