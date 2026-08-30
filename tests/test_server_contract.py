import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ServerScaffoldContractTests(unittest.TestCase):
    def test_server_files_and_api_contract_are_present(self):
        for path in (
            "backend/app/main.py",
            "backend/app/services.py",
            "backend/app/db.py",
            "backend/app/mimo.py",
            "frontend/src/App.tsx",
            "Dockerfile",
            "docker-compose.yml",
            ".env.example",
            "scripts/deploy.sh",
        ):
            self.assertTrue((ROOT / path).exists(), path)
        main = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
        for route in ("/api/session", "/api/profile", "/api/plan", "/api/interview/start", "/api/interview/answer", "/api/interview/end", "/api/feedback", "/health"):
            self.assertIn(route, main)

    def test_runtime_does_not_use_codex_skill_discovery(self):
        runtime = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "backend/app").glob("*.py"))
        self.assertNotIn("subprocess", runtime)
        self.assertIn("mimo-v2.5-pro", (ROOT / ".env.example").read_text(encoding="utf-8"))

    def test_resume_upload_is_temporary_and_secrets_are_ignored(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for item in (".interview/", ".env", "*.pem", "*.key"):
            self.assertIn(item, ignore)
        parser = (ROOT / "backend/app/parsing.py").read_text(encoding="utf-8")
        self.assertIn("finally", parser)
        self.assertIn("unlink", parser)


if __name__ == "__main__":
    unittest.main()
