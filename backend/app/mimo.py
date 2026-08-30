from __future__ import annotations

import json
from dataclasses import dataclass

from .config import settings


class MiMoError(RuntimeError):
    pass


@dataclass
class Completion:
    content: str


class MiMoClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None):
        self.api_key = api_key if api_key is not None else settings.mimo_api_key
        self.base_url = base_url or settings.mimo_base_url
        self.model = model or settings.mimo_model
        self._client = None

    def _openai(self):
        if not self.api_key:
            raise MiMoError("服务器尚未配置 MIMO_API_KEY。")
        if self._client is None:
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=90.0)
            except Exception as exc:  # pragma: no cover
                raise MiMoError(f"无法初始化 MiMo 客户端：{exc}") from exc
        return self._client

    def complete(self, system: str, user: str) -> Completion:
        try:
            response = self._openai().chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.2,
            )
            message = response.choices[0].message
            return Completion(content=message.content or "")
        except Exception as exc:
            raise MiMoError(f"MiMo 请求失败：{exc}") from exc


class DemoMiMoClient(MiMoClient):
    """Deterministic provider used by tests and the fictional local demo."""

    def __init__(self):
        super().__init__(api_key="demo")
        self.interview_count = 0

    def complete(self, system: str, user: str) -> Completion:
        if "资料整理器" in system:
            payload = {
                "education": "简历中列出的计算机相关教育经历",
                "courses": ["数据结构", "机器学习", "计算机视觉", "概率论", "线性代数"],
                "projects": [{"name": "简历中的项目", "details": "按原文保留的方法和角色", "evidence": "用户提供的简历"}],
                "research": ["视觉表征学习与跨模态检索"],
                "skills": ["Python", "PyTorch", "NumPy", "Git"],
                "achievements": [],
                "interests": ["视觉表征学习", "跨模态检索", "模型可解释性"],
                "weak_points": ["尚缺少完整论文复现证据"],
            }
        elif "资料研究模块" in system:
            payload = {
                "research_status": "degraded",
                "key_conclusions": ["视觉表征学习需要明确数据、目标和评价指标"],
                "uncertainty": ["本轮只使用通用知识，目标课题组具体近期方向待核验"],
            }
        elif "面试规划器" in system:
            payload = {
                "duration_minutes": 25,
                "main_question_count": 8,
                "topics": [
                    {"title": "方向基础", "objective": "检查核心概念", "core_question": "请解释你目标方向中的一个核心问题。", "followups": ["它的关键假设是什么？"], "expected_evidence": ["定义、机制、边界"], "evaluation_dimensions": ["专业基础"], "minutes": 3},
                    {"title": "项目深挖", "objective": "核验个人贡献", "core_question": "请具体说明简历中一个项目里你负责的工作。", "followups": ["如何验证结果？"], "expected_evidence": ["角色、方法、结果"], "evaluation_dimensions": ["项目深度"], "minutes": 4},
                    {"title": "实验设计", "objective": "检查因果推理", "core_question": "如果结果提升，你会如何设计对照和消融？", "followups": ["失败时先检查什么？"], "expected_evidence": ["假设、指标、对照"], "evaluation_dimensions": ["科研思维"], "minutes": 4},
                    {"title": "科研开放题", "objective": "检查问题拆解", "core_question": "请提出一个可在一个月内验证的研究问题。", "followups": ["最小实验是什么？"], "expected_evidence": ["可验证问题"], "evaluation_dimensions": ["科研思维"], "minutes": 3},
                    {"title": "方向匹配", "objective": "理解动机", "core_question": "为什么希望加入这个方向的课题组？", "followups": ["你准备先补哪项能力？"], "expected_evidence": ["具体关联"], "evaluation_dimensions": ["方向匹配"], "minutes": 3},
                    {"title": "沟通反思", "objective": "检查复盘能力", "core_question": "回顾一个没有达到预期的尝试，你学到了什么？", "followups": ["下一次会怎么改？"], "expected_evidence": ["事实和反思"], "evaluation_dimensions": ["表达沟通"], "minutes": 3},
                    {"title": "综合追问", "objective": "检查迁移能力", "core_question": "如果数据分布改变，你会优先重新评估什么？", "followups": [], "expected_evidence": ["风险意识"], "evaluation_dimensions": ["专业基础"], "minutes": 2},
                    {"title": "收尾", "objective": "确认学习计划", "core_question": "进入课题组后，你希望如何开始第一周的学习？", "followups": [], "expected_evidence": ["行动计划"], "evaluation_dimensions": ["方向匹配"], "minutes": 2},
                ],
            }
        elif "第一道问题" in user:
            if "结构化审查官" in system:
                question = "请按结论、方法、证据三个部分说明你目标方向中的一个核心问题。"
            elif "温和倾听官" in system or "开放探索官" in system:
                question = "请从你最熟悉的一段经历开始，完整介绍它与你目标方向的联系。"
            else:
                question = "请具体说明你目标方向中的一个核心问题，以及你判断它重要的依据。"
            payload = {"question": question, "topic": "方向基础", "done": False, "clarification": False, "observation": "", "next_action": "next_topic"}
        elif "面试官" in system:
            self.interview_count += 1
            payload = {"question": "请再举一个具体例子说明你的判断。", "topic": "动态追问", "done": False, "clarification": False, "observation": "候选人回答已记录，待继续核验具体依据。", "next_action": "follow_up"}
        elif "反馈教练" in system:
            dims = ["专业基础", "项目深度", "科研思维", "方向匹配", "表达沟通"]
            payload = {
                "overall": "本轮完成了结构化问答，结论仅覆盖已提供的回答证据。",
                "evidence_coverage": "基于本轮转录和候选人档案，证据覆盖有限。",
                "confidence": "中",
                "ratings": {d: {"score": 3, "evidence": ["第 1 轮及候选人档案（待结合具体回答复核）"], "confidence": "低"} for d in dims},
                "strengths": ["愿意说明自己的思路", "能够围绕问题继续回答"],
                "issues": [{"category": "推理", "statement": "需要补充可验证的对照和指标。", "evidence": ["面试转录"], "action": "用假设—指标—对照三行卡片练习。"}],
                "improvement_examples": ["先给结论，再说明机制、证据和局限。"],
                "priority_drills": ["为一个项目写单变量消融表。", "用三分钟解释一个核心概念并录音复盘。", "每天写一张假设—指标—对照—失败解释卡片。"],
                "next_round": "增加项目结果因果性和失败复盘追问。",
            }
        else:
            payload = {}
        return Completion(content=json.dumps(payload, ensure_ascii=False))
