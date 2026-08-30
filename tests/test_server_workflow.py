import os
import tempfile
import unittest

os.environ["MOCK_MIMO"] = "true"
_DATA_DIR = tempfile.TemporaryDirectory(prefix="ai-interviwer-test-")
os.environ["DATA_DIR"] = _DATA_DIR.name

from fastapi.testclient import TestClient

from backend.app.main import app


class ServerWorkflowTests(unittest.TestCase):
    def test_fictional_resume_completes_a_round_and_reuses_profile(self):
        with TestClient(app) as client:
            self.assertEqual(client.post("/api/session").status_code, 200)
            resume = b"# Fictional CV\nPython\nComputer vision project"
            profile = client.post("/api/profile", data={"direction": "计算机视觉"}, files={"resume": ("cv.md", resume, "text/markdown")})
            self.assertEqual(profile.json()["status"], "ready_for_planning")
            plan = client.post("/api/plan")
            self.assertEqual(plan.json()["plan_preview"]["main_question_count"], 8)
            first = client.post("/api/interview/start").json()
            restored = client.get("/api/interview").json()
            self.assertEqual(restored["question"], first["question"])
            request = {"answer": "我会先定义指标和对照。", "request_id": "request-12345678"}
            first_answer = client.post("/api/interview/answer", json=request).json()
            self.assertEqual(client.post("/api/interview/answer", json=request).json(), first_answer)
            client.post("/api/interview/answer", json={"answer": "结束面试", "request_id": "request-end-1234"})
            self.assertEqual(client.post("/api/feedback").json()["status"], "complete")
            next_round = client.post("/api/session/new").json()
            self.assertEqual(next_round["status"], "ready_for_planning")
            self.assertTrue(next_round["profile_complete"])

    def test_profile_revision_invalidates_previous_plan(self):
        with TestClient(app) as client:
            client.post("/api/session")
            client.post("/api/profile", data={"direction": "方向 A"}, files={"resume": ("cv.txt", b"facts")})
            client.post("/api/plan")
            updated = client.post("/api/profile", data={"direction": "方向 B"}, files={"resume": ("cv.txt", b"new facts")})
            self.assertEqual(updated.json()["status"], "ready_for_planning")
            self.assertEqual(client.post("/api/interview/start").status_code, 409)


if __name__ == "__main__":
    unittest.main()
