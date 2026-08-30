import unittest
from pathlib import Path

from pydantic import ValidationError

from backend.app.schemas import FeedbackPayload, PlanPayload, ResearchBriefPayload


ROOT = Path(__file__).resolve().parents[1]


class ServerScaffoldContractTests(unittest.TestCase):
    def test_feedback_contract_exposes_one_probability_and_two_gap_groups(self):
        public = FeedbackPayload.model_validate(
            {
                "interview_pass_probability": 68,
                "overall": "总结",
                "evidence_coverage": "覆盖充分",
                "confidence": "高",
                "strengths": ["能给出证据"],
                "professional_knowledge_gaps": [],
                "interview_skill_gaps": [],
                "improvement_examples": [],
                "priority_drills": ["练习一", "练习二", "练习三"],
                "next_round": "继续追问",
            }
        )
        self.assertGreaterEqual(public.interview_pass_probability, 5)
        self.assertLessEqual(public.interview_pass_probability, 95)
        self.assertNotIn("ratings", public.model_dump())
        self.assertIn("professional_knowledge_gaps", public.model_dump())
        self.assertIn("interview_skill_gaps", public.model_dump())

    def test_short_model_plan_is_completed_to_minimum_topic_count(self):
        topics = [
            {
                "title": f"主题 {index}",
                "objective": "检查一个面试维度",
                "core_question": "请说明你的判断和依据。",
                "followups": [],
                "expected_evidence": ["事实"],
                "evaluation_dimensions": ["科研思维"],
                "minutes": 2,
            }
            for index in range(7)
        ]
        plan = PlanPayload.model_validate({"duration_minutes": 25, "main_question_count": 7, "topics": topics})
        self.assertEqual(len(plan.topics), 8)
        self.assertEqual(plan.main_question_count, 8)

    def test_server_files_and_api_contract_are_present(self):
        for path in (
            "backend/app/main.py",
            "backend/app/services.py",
            "backend/app/db.py",
            "backend/app/interviewer_styles.py",
            "backend/app/mimo.py",
            "backend/app/runner.py",
            "backend/runner_service.py",
            "backend/runner_worker.py",
            "backend/migrations/versions/0002_interviewer_styles.py",
            "backend/migrations/versions/0003_practical_tasks.py",
            "frontend/src/App.tsx",
            "Dockerfile",
            "docker-compose.yml",
            "runner.Dockerfile",
            ".env.example",
            "scripts/deploy.sh",
        ):
            self.assertTrue((ROOT / path).exists(), path)
        main = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
        for route in ("/api/session", "/api/profile", "/api/plan", "/api/interviewer-styles", "/api/interview/start", "/api/interview/answer", "/api/interview/tasks/{task_id}/run", "/api/interview/tasks/{task_id}/submit", "/api/interview/transcribe", "/api/interview/end", "/api/feedback", "/health"):
            self.assertIn(route, main)

    def test_audio_is_streamed_in_memory_and_not_persisted(self):
        main = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
        asr = (ROOT / "backend/app/asr.py").read_text(encoding="utf-8")
        requirements = (ROOT / "backend/requirements.txt").read_text(encoding="utf-8")
        env = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("request.stream()", main)
        self.assertNotIn("open(", asr)
        self.assertNotIn("Temporary", asr)
        self.assertIn("faster-whisper", requirements)
        self.assertIn("LOCAL_ASR_MODEL", env)
        self.assertNotIn("ASR_API_KEY", env)

    def test_runtime_does_not_use_codex_skill_discovery(self):
        runtime = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "backend/app").glob("*.py"))
        self.assertNotIn("subprocess", runtime)
        self.assertNotIn("web_search", runtime.lower())
        self.assertNotIn("MIMO_WEB_SEARCH_ENABLED", (ROOT / ".env.example").read_text(encoding="utf-8"))
        self.assertIn("mimo-v2.5-pro", (ROOT / ".env.example").read_text(encoding="utf-8"))

    def test_research_contract_is_offline_only(self):
        brief = ResearchBriefPayload.model_validate(
            {
                "research_status": "degraded",
                "key_conclusions": ["通用结论"],
                "uncertainty": [],
                "sources": [{"url": "https://example.com"}],
            }
        )
        self.assertEqual(brief.research_status, "degraded")
        self.assertNotIn("sources", brief.model_dump())
        with self.assertRaises(ValidationError):
            ResearchBriefPayload.model_validate({"research_status": "verified"})

    def test_resume_upload_is_temporary_and_secrets_are_ignored(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for item in (".interview/", ".env", "*.pem", "*.key"):
            self.assertIn(item, ignore)
        parser = (ROOT / "backend/app/parsing.py").read_text(encoding="utf-8")
        self.assertIn("finally", parser)
        self.assertIn("unlink", parser)


if __name__ == "__main__":
    unittest.main()
