"""Test UI API: upload, poll, download, and jobs surviving a server restart."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import fs_translator.web.app as web
import make_sample


class WebTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_dir = web.WORK_DIR
        web.WORK_DIR = Path(self.tmp.name) / "web"
        web._jobs.clear()
        self.client = TestClient(web.app)
        self.sample = make_sample.build(Path(self.tmp.name) / "sample.docx")

    def tearDown(self):
        web.WORK_DIR = self.old_dir
        web._jobs.clear()
        self.tmp.cleanup()

    def _run_job(self):
        with open(self.sample, "rb") as f:
            job = self.client.post("/api/jobs", files={"file": ("sample.docx", f)},
                                   data={"model": web.FAKE, "terms": "gcc"}).json()
        for _ in range(100):
            state = self.client.get(f"/api/jobs/{job['id']}").json()
            if state["state"] in ("done", "error"):
                return state
            time.sleep(0.1)
        self.fail("job did not finish")

    def test_upload_translate_download(self):
        job = self._run_job()
        self.assertEqual(job["state"], "done", job["error"])
        r = self.client.get(f"/api/jobs/{job['id']}/download")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b"PK"))           # a zip, i.e. a .docx

    def test_finished_job_survives_restart(self):
        job = self._run_job()
        web._jobs.clear()                                       # what a restart does
        again = self.client.get(f"/api/jobs/{job['id']}").json()
        self.assertEqual(again["state"], "done")
        self.assertIsNotNone(again["report"])
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}/download").status_code, 200)

    def test_job_from_before_job_json_is_rebuilt(self):
        job = self._run_job()
        (web.WORK_DIR / job["id"] / "job.json").unlink()        # like jobs made before this fix
        web._jobs.clear()
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}/download").status_code, 200)

    def test_running_job_is_reported_as_interrupted(self):
        job_dir = web.WORK_DIR / "abc123"
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(json.dumps(
            {"id": "abc123", "filename": "x.docx", "model": "m", "limit": None, "state": "translating"}))
        state = self.client.get("/api/jobs/abc123").json()
        self.assertEqual(state["state"], "error")
        self.assertIn("restart", state["error"])

    def test_clear_deletes_finished_jobs_and_keeps_running_ones(self):
        done = self._run_job()
        running = web.WORK_DIR / "run123"
        running.mkdir(parents=True)
        web._jobs["run123"] = web.Job("run123", "x.docx", "m", None, state="translating")
        result = self.client.delete("/api/jobs").json()
        self.assertEqual(result, {"removed": 1, "kept_running": 1})
        self.assertFalse((web.WORK_DIR / done["id"]).exists())             # files are gone
        self.assertTrue(running.exists())
        self.assertEqual([j["id"] for j in self.client.get("/api/jobs").json()], ["run123"])
        self.assertEqual(self.client.get(f"/api/jobs/{done['id']}/download").status_code, 404)

    def test_unknown_and_unsafe_ids(self):
        self.assertEqual(self.client.get("/api/jobs/nope/download").status_code, 404)
        self.assertEqual(self.client.get("/api/jobs/..%2F..%2Fetc").status_code, 404)


if __name__ == "__main__":
    unittest.main()
