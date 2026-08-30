from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL_NAMES = (
    "interview-onboarding",
    "interview-planner",
    "mock-interviewer",
    "interview-feedback",
)


class FrameworkContractTests(unittest.TestCase):
    def test_project_orchestration_and_privacy_contract(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for name in SKILL_NAMES:
            self.assertIn(f"${name}", agents)
        self.assertIn(".interview/", ignore)
        self.assertIn("profile_revision", agents)
        self.assertIn("plan_profile_revision", agents)

    def test_each_skill_has_valid_minimal_metadata(self):
        for name in SKILL_NAMES:
            skill_dir = ROOT / ".agents" / "skills" / name
            skill = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            self.assertRegex(skill, rf"(?m)^name: {re.escape(name)}$")
            self.assertRegex(skill, r"(?m)^description: .+")
            metadata = (skill_dir / "agents" / "openai.yaml").read_text(encoding="utf-8")
            self.assertIn("allow_implicit_invocation: true", metadata)
            self.assertIn("default_prompt:", metadata)
            self.assertIn(f"${name}", metadata)

    def test_demo_is_explicitly_fictional(self):
        cv = (ROOT / "demo" / "fictional-cv.md").read_text(encoding="utf-8")
        brief = (ROOT / "demo" / "fictional-research-brief.md").read_text(encoding="utf-8")
        self.assertIn("虚构", cv)
        self.assertIn("research_status: degraded", brief)
        self.assertIn("未联网核验", brief)
        self.assertNotIn("@", cv)

    def test_behavioral_constraints_are_documented(self):
        onboarding = (ROOT / ".agents/skills/interview-onboarding/SKILL.md").read_text(encoding="utf-8")
        planner = (ROOT / ".agents/skills/interview-planner/SKILL.md").read_text(encoding="utf-8")
        interviewer = (ROOT / ".agents/skills/mock-interviewer/SKILL.md").read_text(encoding="utf-8")
        feedback = (ROOT / ".agents/skills/interview-feedback/SKILL.md").read_text(encoding="utf-8")
        for file_type in ("PDF", "DOCX", "Markdown", "TXT"):
            self.assertIn(file_type, onboarding)
        for phrase in ("8–12", "research_status: degraded", "不联网", "预期证据"):
            self.assertIn(phrase, planner)
        for phrase in ("只发送第一个问题", "不公布分数", "ASR", "ready_for_feedback"):
            self.assertIn(phrase, interviewer)
        for phrase in ("模拟面试通过概率", "专业知识方面不足", "面试技巧方面不足", "科研思维", "三个优先训练动作"):
            self.assertIn(phrase, feedback)


if __name__ == "__main__":
    unittest.main()
