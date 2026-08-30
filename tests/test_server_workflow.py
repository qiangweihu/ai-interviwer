import os
import tempfile
import unittest

os.environ["MOCK_MIMO"] = "true"
_DATA_DIR = tempfile.TemporaryDirectory(prefix="ai-interviwer-test-")
os.environ["DATA_DIR"] = _DATA_DIR.name

from fastapi.testclient import TestClient

from backend.app.db import InterviewRun, PracticalSubmission, SessionLocal
from backend.app.main import app
from backend.app.schemas import FeedbackAssessmentPayload
from backend.app.services import _feedback_probability


class ServerWorkflowTests(unittest.TestCase):
    def _start_until_practical(self, client):
        client.post("/api/session")
        client.post("/api/profile", data={"direction": "计算机视觉"}, files={"resume": ("cv.txt", b"Python")})
        client.post("/api/plan")
        current = client.post("/api/interview/start").json()
        for index in range(20):
            if current.get("task", {}).get("type") != "oral":
                return current
            current = client.post("/api/interview/answer", json={"answer": "回答", "request_id": f"practical-answer-{index:08d}"}).json()
        self.fail("mixed plan did not reach a practical task")

    def test_practical_task_public_run_hidden_submit_and_private_field_stripping(self):
        with TestClient(app) as client:
            current = self._start_until_practical(client)
            task = current["task"]
            self.assertIn(task["type"], {"coding", "code_review", "practical"})
            self.assertNotIn("hidden_tests", task)
            self.assertNotIn("reference_solution", task)
            self.assertNotIn("reference_language", task)
            self.assertNotIn("rubric", task)
            source = "import sys\ndata=list(map(int,sys.stdin.read().split())); print(sum(data[1:]) if data else 0)"
            trial = client.post(f"/api/interview/tasks/{task['id']}/run", json={"request_id": "trial-request-1234", "language": "python", "source": source})
            self.assertEqual(trial.status_code, 200)
            self.assertEqual(trial.json()["public"], True)
            self.assertEqual(client.post(f"/api/interview/tasks/{task['id']}/run", json={"request_id": "trial-request-1234", "language": "python", "source": source}).json(), trial.json())
            submitted = client.post(f"/api/interview/tasks/{task['id']}/submit", json={"request_id": "final-request-1234", "language": "python", "source": source, "explanation": "先处理输入边界。"})
            self.assertEqual(submitted.status_code, 200)
            self.assertTrue(submitted.json()["locked"])
            if not submitted.json()["done"]:
                self.assertNotEqual(submitted.json().get("task", {}).get("id"), task["id"])
            retried = client.post(f"/api/interview/tasks/{task['id']}/submit", json={"request_id": "final-request-1234", "language": "python", "source": source, "explanation": "先处理输入边界。"})
            self.assertEqual(retried.status_code, 200)
            self.assertEqual(retried.json()["result"], submitted.json()["result"])
            with SessionLocal() as db:
                submissions = db.query(PracticalSubmission).all()
                self.assertTrue(submissions)
                self.assertTrue(submissions[-1].locked)

    def test_code_review_can_submit_explanation_without_patch(self):
        with TestClient(app) as client:
            current = self._start_until_practical(client)
            coding = current["task"]
            source = "import sys\ndata=list(map(int,sys.stdin.read().split())); print(sum(data[1:]) if data else 0)"
            next_item = client.post(
                f"/api/interview/tasks/{coding['id']}/submit",
                json={"request_id": "coding-final-explanation-test", "language": "python", "source": source},
            ).json()
            review = next_item.get("task")
            self.assertEqual(review["type"], "code_review")
            submitted = client.post(
                f"/api/interview/tasks/{review['id']}/submit",
                json={
                    "request_id": "review-explanation-only-test",
                    "language": "python",
                    "source": "",
                    "explanation": "空输入会触发除零；最小反例是空行。",
                },
            )
            self.assertEqual(submitted.status_code, 200)
            self.assertEqual(submitted.json()["result"]["status"], "not_executed")
            self.assertEqual(submitted.json()["result"]["total"], 0)

    def test_feedback_probability_is_monotonic_and_sparse_evidence_is_shrunk(self):
        def assessment(score: int, confidence: str = "高"):
            return FeedbackAssessmentPayload.model_validate(
                {
                    "overall": "总结",
                    "evidence_coverage": "覆盖",
                    "confidence": confidence,
                    "dimension_scores": {
                        name: {"score": score, "evidence": ["第 1 轮"], "confidence": confidence}
                        for name in ("专业知识与基础", "项目与科研经历深度", "科研思维", "方向匹配", "面试表达与应答")
                    },
                    "priority_drills": ["练习一", "练习二", "练习三"],
                    "next_round": "继续追问",
                }
            )

        low = _feedback_probability(assessment(40), candidate_turn_count=4)
        high = _feedback_probability(assessment(85), candidate_turn_count=4)
        sparse = _feedback_probability(assessment(85), candidate_turn_count=1)
        self.assertLess(low, high)
        self.assertLess(sparse, high)
        self.assertGreater(sparse, 50)

    def test_legacy_feedback_cache_is_regenerated_from_the_transcript(self):
        with TestClient(app) as client:
            client.post("/api/session")
            client.post("/api/profile", data={"direction": "方向"}, files={"resume": ("cv.txt", b"facts")})
            client.post("/api/plan")
            client.post("/api/interview/start")
            client.post("/api/interview/end")
            run_id = client.get("/api/session").json()["current_run_id"]
            with SessionLocal() as db:
                run = db.get(InterviewRun, run_id)
                self.assertIsNotNone(run)
                if run is None:  # keep the type checker and runtime path explicit
                    return
                run.feedback_json = '{"overall":"旧版","evidence_coverage":"旧版","confidence":"中","ratings":{},"priority_drills":["a","b","c"],"next_round":"旧版"}'
                db.commit()
            response = client.get("/api/feedback")
            self.assertEqual(response.status_code, 200)
            feedback = response.json()["feedback"]
            self.assertEqual(feedback["feedback_version"], "2")
            self.assertNotIn("ratings", feedback)

    def test_interviewer_style_catalog_and_legacy_aliases(self):
        with TestClient(app) as client:
            catalog = client.get("/api/interviewer-styles")
            self.assertEqual(catalog.status_code, 200)
            payload = catalog.json()
            self.assertEqual(len(payload["presets"]), 8)
            self.assertEqual(
                {item["preset_id"] for item in payload["presets"]},
                {
                    "structured_examiner",
                    "investigative_examiner",
                    "guided_interviewer",
                    "adaptive_guide",
                    "patient_examiner",
                    "deep_dive_examiner",
                    "supportive_listener",
                    "open_explorer",
                },
            )
            client.post("/api/session")
            client.post("/api/profile", data={"direction": "计算机视觉"}, files={"resume": ("cv.txt", b"facts")})
            planned = client.post(
                "/api/plan",
                json={"interviewer_style": {"control": "listener", "tone": "strict", "plan_adherence": "flexible"}},
            )
            self.assertEqual(planned.status_code, 200)
            selected = planned.json()["interviewer_style"]
            self.assertEqual(selected["preset_id"], "deep_dive_examiner")
            self.assertEqual(selected["initiative"], "listening")
            self.assertEqual(selected["structure"], "adaptive")
            self.assertIn("完整", client.post("/api/interview/start").json()["question"])

    def test_invalid_interviewer_style_is_rejected_instead_of_defaulting(self):
        with TestClient(app) as client:
            client.post("/api/session")
            client.post("/api/profile", data={"direction": "方向"}, files={"resume": ("cv.txt", b"facts")})
            response = client.post(
                "/api/plan",
                json={"interviewer_style": {"control": "aggressive", "tone": "friendly", "plan_adherence": "structured"}},
            )
            self.assertEqual(response.status_code, 422)

    def test_style_snapshot_is_reused_for_next_round(self):
        with TestClient(app) as client:
            client.post("/api/session")
            client.post("/api/profile", data={"direction": "方向"}, files={"resume": ("cv.txt", b"facts")})
            selected = {"initiative": "listening", "tone": "friendly", "structure": "adaptive"}
            planned = client.post("/api/plan", json={"interviewer_style": selected}).json()
            self.assertEqual(planned["interviewer_style"]["preset_id"], "open_explorer")
            client.post("/api/interview/start")
            client.post("/api/interview/end")
            next_round = client.post("/api/session/new")
            self.assertEqual(next_round.status_code, 200)
            self.assertEqual(next_round.json()["interviewer_style"]["preset_id"], "open_explorer")
            replanned = client.post("/api/plan")
            self.assertEqual(replanned.json()["interviewer_style"]["preset_id"], "open_explorer")

    def test_fictional_resume_completes_a_round_and_reuses_profile(self):
        with TestClient(app) as client:
            self.assertEqual(client.post("/api/session").status_code, 200)
            resume = b"# Fictional CV\nPython\nComputer vision project"
            profile = client.post("/api/profile", data={"direction": "计算机视觉"}, files={"resume": ("cv.md", resume, "text/markdown")})
            self.assertEqual(profile.json()["status"], "ready_for_planning")
            plan = client.post("/api/plan")
            self.assertEqual(plan.json()["plan_preview"]["main_question_count"], 8)
            first = client.post("/api/interview/start").json()
            speech_config = client.get("/api/speech/config").json()
            self.assertTrue(speech_config["enabled"])
            transcription = client.post(
                "/api/interview/transcribe",
                content=b"fictional-webm-audio",
                headers={"Content-Type": "audio/webm"},
            )
            self.assertEqual(transcription.status_code, 200)
            self.assertIn("口语回答", transcription.json()["text"])
            restored = client.get("/api/interview").json()
            self.assertEqual(restored["question"], first["question"])
            request = {"answer": "我会先定义指标和对照。", "request_id": "request-12345678"}
            first_answer = client.post("/api/interview/answer", json=request).json()
            self.assertEqual(client.post("/api/interview/answer", json=request).json(), first_answer)
            client.post("/api/interview/answer", json={"answer": "结束面试", "request_id": "request-end-1234"})
            feedback_response = client.post("/api/feedback").json()
            self.assertEqual(feedback_response["status"], "complete")
            feedback = feedback_response["feedback"]
            self.assertIn("interview_pass_probability", feedback)
            self.assertNotIn("ratings", feedback)
            self.assertIn("professional_knowledge_gaps", feedback)
            self.assertIn("interview_skill_gaps", feedback)
            self.assertRegex(str(feedback["interview_pass_probability"]), r"^(?:[5-9]|[1-8][0-9]|9[0-5])$")
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
