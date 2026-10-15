"""Regression tests for admin-only delete and guest-capped history.

Run from the repo root:  .venv/bin/python -m unittest discover -s backend/tests -v
"""
import base64
import dataclasses
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import app as app_module
from backend import auth, db
from backend.config import settings as real_settings
from backend.export import DELIMITER_LEFT, DELIMITER_RIGHT, delimiter_line


def _basic(user: str, password: str) -> dict[str, str]:
    raw = f"{user}:{password}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


class AdminAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.db_path = str(Path(cls._tmp.name) / "test.db")
        cls.test_settings = dataclasses.replace(
            real_settings,
            database_path=cls.db_path,
            admin_username="testadmin",
            admin_password="s3cret!",
        )
        cls.admin = _basic("testadmin", "s3cret!")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        for suffix in ("", "-wal", "-shm"):
            p = Path(self.db_path + suffix)
            if p.exists():
                p.unlink()
        db.init_db(self.db_path)
        auth._sessions.clear()
        # Seed 8 distinct (url, length) pairs; pair 0 gets a second version.
        self.first_ids: list[int] = []
        for i in range(8):
            rows = db.add_summary(
                url=f"https://www.youtube.com/watch?v=vid{i:07d}",
                video_id=f"vid{i:07d}",
                title=f"Video {i}" + (" uniquetoken" if i == 3 else ""),
                length="quick" if i % 2 == 0 else "medium",
                summary=f"Summary body {i}",
                model="test",
                transcript_chars=1000,
                max_versions=5,
            )
            self.first_ids.append(rows[0]["id"])
        db.add_summary(
            url="https://www.youtube.com/watch?v=vid0000000",
            video_id="vid0000000",
            title="Video 0",
            length="quick",
            summary="second version body",
            model="test",
            transcript_chars=1000,
            max_versions=5,
        )
        for target in (app_module, "backend.config"):
            p = patch.object(target, "settings", self.test_settings) if target is app_module else patch(
                "backend.config.settings", self.test_settings
            )
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(app_module.app)

    def _total_versions(self) -> int:
        _, total = db.list_all_summaries()
        return total

    def test_delete_requires_auth(self):
        res = self.client.delete(f"/api/summaries/{self.first_ids[0]}")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(self._total_versions(), 9)

    def test_delete_rejects_bad_credentials(self):
        for headers in (
            _basic("testadmin", "wrong"),
            _basic("nobody", "s3cret!"),
            {"Authorization": "Bearer bogus-token"},
            {"Authorization": "Basic !!!not-base64!!!"},
            {"Authorization": "Bearer "},
        ):
            res = self.client.delete(f"/api/summaries/{self.first_ids[0]}", headers=headers)
            self.assertEqual(res.status_code, 401, headers)
        self.assertEqual(self._total_versions(), 9)

    def test_delete_with_basic_auth(self):
        res = self.client.delete(f"/api/summaries/{self.first_ids[0]}", headers=self.admin)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"deleted": True})
        self.assertEqual(self._total_versions(), 8)
        res = self.client.delete(f"/api/summaries/{self.first_ids[0]}", headers=self.admin)
        self.assertEqual(res.status_code, 404)

    def test_login_token_flow(self):
        bad = self.client.post("/api/login", json={"username": "testadmin", "password": "wrong"})
        self.assertEqual(bad.status_code, 401)
        good = self.client.post("/api/login", json={"username": "testadmin", "password": "s3cret!"})
        self.assertEqual(good.status_code, 200)
        token = good.json()["token"]
        bearer = {"Authorization": f"Bearer {token}"}
        res = self.client.delete(f"/api/summaries/{self.first_ids[1]}", headers=bearer)
        self.assertEqual(res.status_code, 200)
        res = self.client.post("/api/logout", headers=bearer)
        self.assertEqual(res.status_code, 200)
        res = self.client.delete(f"/api/summaries/{self.first_ids[2]}", headers=bearer)
        self.assertEqual(res.status_code, 401)

    def test_me_reports_admin_state(self):
        self.assertEqual(self.client.get("/api/me").json(), {"is_admin": False})
        res = self.client.get("/api/me", headers=self.admin)
        self.assertEqual(res.json(), {"is_admin": True})

    def test_guest_history_capped_at_five(self):
        for params in ("", "?limit=20", "?limit=100"):
            res = self.client.get(f"/api/history{params}")
            self.assertEqual(res.status_code, 200)
            body = res.json()
            self.assertFalse(body["is_admin"])
            self.assertEqual(len(body["items"]), 5)
        # Most recent first: pair 0's second version is the newest row overall.
        self.assertEqual(self.client.get("/api/history").json()["items"][0]["video_id"], "vid0000000")

    def test_guest_search_filter_params_ignored(self):
        res = self.client.get("/api/history?q=uniquetoken&length=quick&limit=100")
        body = res.json()
        self.assertFalse(body["is_admin"])
        self.assertEqual(len(body["items"]), 5)

    def test_admin_history_full_search_and_filter(self):
        res = self.client.get("/api/history?limit=20", headers=self.admin)
        body = res.json()
        self.assertTrue(body["is_admin"])
        self.assertEqual(len(body["items"]), 8)
        res = self.client.get("/api/history?q=uniquetoken", headers=self.admin)
        items = res.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["video_id"], "vid0000003")
        res = self.client.get("/api/history?length=quick", headers=self.admin)
        self.assertEqual(len(res.json()["items"]), 4)
        res = self.client.get("/api/history?length=bogus", headers=self.admin)
        self.assertEqual(res.status_code, 400)

    def test_admin_summaries_endpoint(self):
        res = self.client.get("/api/admin/summaries")
        self.assertEqual(res.status_code, 401)
        res = self.client.get("/api/admin/summaries", headers=self.admin)
        body = res.json()
        self.assertEqual(body["total"], 9)
        self.assertEqual(len(body["items"]), 9)
        res = self.client.get("/api/admin/summaries?q=second+version", headers=self.admin)
        self.assertEqual(res.json()["total"], 1)
        res = self.client.get("/api/admin/summaries?video_id=vid0000000", headers=self.admin)
        self.assertEqual(res.json()["total"], 2)
        res = self.client.get("/api/admin/summaries?length=medium", headers=self.admin)
        self.assertEqual(res.json()["total"], 4)
        res = self.client.get("/api/admin/summaries?limit=3&offset=0", headers=self.admin)
        body = res.json()
        self.assertEqual((body["total"], len(body["items"]), body["limit"], body["offset"]), (9, 3, 3, 0))

    def test_export_requires_auth(self):
        res = self.client.get("/api/admin/export")
        self.assertEqual(res.status_code, 401)

    def test_export_all_delimited(self):
        res = self.client.get("/api/admin/export", headers=self.admin)
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/markdown", res.headers["content-type"])
        self.assertIn("attachment", res.headers["content-disposition"])
        self.assertIn("recap-export-", res.headers["content-disposition"])
        body = res.text
        delimiters = re.findall(r"^@+ \[.+\] @+$", body, re.M)
        self.assertEqual(len(delimiters), 9)
        self.assertIn("[Video 3 uniquetoken]", body)
        self.assertIn("Summary body 0", body)
        self.assertIn("second version body", body)

    def test_export_with_filters(self):
        res = self.client.get("/api/admin/export?q=uniquetoken", headers=self.admin)
        delimiters = re.findall(r"^@+ \[.+\] @+$", res.text, re.M)
        self.assertEqual(len(delimiters), 1)
        res = self.client.get("/api/admin/export?length=medium", headers=self.admin)
        delimiters = re.findall(r"^@+ \[.+\] @+$", res.text, re.M)
        self.assertEqual(len(delimiters), 4)

    def test_export_ids_subset_in_given_order(self):
        picked = [self.first_ids[3], self.first_ids[0]]
        res = self.client.get(f"/api/admin/export?ids={picked[0]},{picked[1]}", headers=self.admin)
        self.assertEqual(res.status_code, 200)
        delimiters = re.findall(r"^@+ \[.+\] @+$", res.text, re.M)
        self.assertEqual(len(delimiters), 2)
        self.assertLess(res.text.index("[Video 3 uniquetoken]"), res.text.index("[Video 0]"))

    def test_export_invalid_ids_rejected(self):
        res = self.client.get("/api/admin/export?ids=1,abc", headers=self.admin)
        self.assertEqual(res.status_code, 400)
        res = self.client.get("/api/admin/export?length=bogus", headers=self.admin)
        self.assertEqual(res.status_code, 400)

    def test_export_unknown_ids_yield_empty_file(self):
        res = self.client.get("/api/admin/export?ids=999999", headers=self.admin)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.text, "")

    def test_delimiter_shape(self):
        self.assertEqual((len(DELIMITER_LEFT), len(DELIMITER_RIGHT)), (42, 48))
        self.assertRegex(delimiter_line("Hello"), r"^@+ \[Hello\] @+$")
        self.assertIn("Untitled", delimiter_line(""))


if __name__ == "__main__":
    unittest.main()
