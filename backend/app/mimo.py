from __future__ import annotations

import json
from dataclasses import dataclass

from .config import settings


class MiMoError(RuntimeError):
    pass


@dataclass
class Completion:
    content: str


# Fully fictional practical-task fixtures used by the local demo. They are
# selected only when the requested direction explicitly calls for the task;
# production planning still comes from the configured model and runner.
DEMO_PRACTICAL_TASKS = {
    "cpp": {
        "title": "C++ 边界实现",
        "objective": "检查标准输入输出、边界处理和复杂度判断。",
        "core_question": "请用 C++20 完成题目，并说明你如何处理 n=0。",
        "followups": ["如果不能使用额外数组，你会怎么改？"],
        "expected_evidence": ["可编译代码、边界处理、复杂度说明"],
        "evaluation_dimensions": ["专业知识与基础", "科研思维"],
        "minutes": 10,
        "constraints": ["第一行给出 n，第二行给出 n 个整数", "n 在 0 到 1000 之间，输出最大值；n=0 输出 0"],
        "type": "coding",
        "language_options": ["cpp"],
        "starter_code": "#include <iostream>\nint main() {\n    // 从标准输入读取数据，并向标准输出写结果\n}\n",
        "public_samples": [{"input": "4\n1 7 3 2\n", "output": "7\n", "explanation": "输出序列最大值。"}],
        "hidden_tests": [{"input": "0\n", "output": "0\n"}, {"input": "3\n-4 -2 -9\n", "output": "-2\n"}],
        "reference_solution": "#include <iostream>\n#include <algorithm>\nint main(){ int n; if(!(std::cin>>n)||n<=0){std::cout<<0<<'\\n'; return 0;} int x, ans; std::cin>>ans; for(int i=1;i<n;i++){std::cin>>x; ans=std::max(ans,x);} std::cout<<ans<<'\\n'; }",
        "reference_language": "cpp",
        "rubric": ["正确处理 n=0 和负数", "符合 C++20 标准输入输出", "能说明 O(n) 复杂度"],
    },
    "sql": {
        "title": "SQLite 只读查询",
        "objective": "检查把业务问题转成只读 SQL，并验证聚合结果。",
        "core_question": "请写一条只读 SELECT/CTE 查询，按类别统计虚构实验事件。",
        "followups": ["如果要保留没有事件的类别，你会如何调整？"],
        "expected_evidence": ["查询结果、聚合逻辑、边界说明"],
        "evaluation_dimensions": ["专业知识与基础", "科研思维"],
        "minutes": 10,
        "constraints": ["只能使用 SELECT 或 CTE，不得修改数据库", "结果按 category 升序返回"],
        "type": "practical",
        "practical_type": "sql",
        "language_options": ["sql"],
        "materials": {"schema": "CREATE TABLE demo_events(category TEXT, outcome TEXT);", "seed": "INSERT INTO demo_events VALUES ('vision','ok'),('vision','retry'),('retrieval','ok');"},
        "public_samples": [{"input": "", "rows": [["retrieval", 1], ["vision", 2]], "explanation": "按类别统计事件数。"}],
        "hidden_tests": [{"input": "", "rows": [["retrieval", 1], ["vision", 2]]}],
        "reference_solution": "SELECT category, COUNT(*) FROM demo_events GROUP BY category ORDER BY category",
        "reference_language": "sql",
        "rubric": ["只读查询", "分组计数正确", "结果顺序稳定"],
    },
    "experiment_analysis": {
        "title": "实验结果与日志分析",
        "objective": "检查从指标和日志提出可验证的原因判断。",
        "core_question": "请根据材料提交结构化判断、依据和下一步验证方案。",
        "followups": ["你会优先控制哪个变量？"],
        "expected_evidence": ["明确判断、材料证据、最小验证方案"],
        "evaluation_dimensions": ["科研思维", "专业知识与基础"],
        "minutes": 10,
        "constraints": ["判断必须引用至少一项材料证据", "验证方案要能区分两个候选原因"],
        "type": "practical",
        "practical_type": "experiment_analysis",
        "language_options": ["text"],
        "materials": {"metrics": "baseline accuracy=0.82\nnew accuracy=0.77\nvalidation size unchanged", "logs": "batch=18 warning: label distribution drift\nbatch=19 warning: label distribution drift"},
        "rubric": ["结论与指标一致", "引用日志证据", "提出可执行的对照验证"],
    },
}


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
            if "优先让候选人完整展开" in user:
                first_question = "请从你最熟悉的一段经历开始，完整介绍它与你目标方向的联系。"
            elif "主动控制面试节奏" in user:
                first_question = "请具体说明你目标方向中的一个核心问题，以及你判断它重要的依据。"
            else:
                first_question = "请说明你目标方向中的一个核心问题，以及你会如何验证它。"
            payload = {
                "plan_version": 2,
                "duration_minutes": 35,
                "main_question_count": 8,
                "topics": [
                    {"title": "方向基础", "objective": "检查核心概念", "core_question": first_question, "followups": ["它的关键假设是什么？"], "expected_evidence": ["定义、机制、边界"], "evaluation_dimensions": ["专业知识与基础"], "minutes": 3},
                    {"title": "项目深挖", "objective": "核验个人贡献", "core_question": "请具体说明简历中一个项目里你负责的工作。", "followups": ["如何验证结果？"], "expected_evidence": ["角色、方法、结果"], "evaluation_dimensions": ["项目与科研经历深度"], "minutes": 4},
                    {"title": "实验设计", "objective": "检查因果推理", "core_question": "如果结果提升，你会如何设计对照和消融？", "followups": ["失败时先检查什么？"], "expected_evidence": ["假设、指标、对照"], "evaluation_dimensions": ["科研思维"], "minutes": 4},
                    {"title": "科研开放题", "objective": "检查问题拆解", "core_question": "请提出一个可在一个月内验证的研究问题。", "followups": ["最小实验是什么？"], "expected_evidence": ["可验证问题"], "evaluation_dimensions": ["科研思维"], "minutes": 3},
                    {"title": "方向匹配", "objective": "理解动机", "core_question": "为什么希望加入这个方向的课题组？", "followups": ["你准备先补哪项能力？"], "expected_evidence": ["具体关联"], "evaluation_dimensions": ["方向匹配"], "minutes": 3},
                    {"title": "沟通反思", "objective": "检查复盘能力", "core_question": "回顾一个没有达到预期的尝试，你学到了什么？", "followups": ["下一次会怎么改？"], "expected_evidence": ["事实和反思"], "evaluation_dimensions": ["面试表达与应答"], "minutes": 3},
                    {"title": "算法实现实操", "objective": "检查把问题拆解为可执行算法并处理边界条件的能力。", "core_question": "请在编辑器中完成题目，并说明你的复杂度判断。", "followups": ["如果输入规模扩大，你会如何优化？"], "expected_evidence": ["可运行代码、边界处理、复杂度说明"], "evaluation_dimensions": ["专业知识与基础", "科研思维"], "minutes": 10, "constraints": ["第一行给出 n，第二行给出 n 个整数", "n 可为 0，结果输出一个整数"], "type": "coding", "language_options": ["python", "cpp"], "starter_code": "# 读取标准输入并将结果写到标准输出\n", "public_samples": [{"input": "4\n1 2 3 4\n", "output": "10\n", "explanation": "求整数序列的和。"}], "hidden_tests": [{"input": "0\n\n", "output": "0\n"}, {"input": "3\n-1 5 2\n", "output": "6\n"}], "reference_solution": "import sys\ndata=list(map(int,sys.stdin.read().split())); print(sum(data[1:]) if data else 0)", "reference_language": "python", "rubric": ["正确处理空输入和负数", "输出符合要求", "能解释复杂度"]},
                    {"title": "代码理解与调试", "objective": "检查定位逻辑错误、解释执行过程和提出修复方案的能力。", "core_question": "请指出下面代码在边界输入下的问题，说明原因并提交修正版（可选）。", "followups": ["你会用什么最小测试先复现？"], "expected_evidence": ["问题定位、反例、修复理由"], "evaluation_dimensions": ["专业知识与基础", "科研思维"], "minutes": 8, "constraints": ["解释空输入与单元素输入", "修正版使用标准输入/输出"], "type": "code_review", "language_options": ["python"], "starter_code": "import sys\nvalues = list(map(float, sys.stdin.read().split()))\nprint(sum(values) / (len(values) - 1))\n", "materials": {"prompt": "解释空输入和单元素输入的行为，指出分母问题，并在愿意时提交 stdin/stdout 修正版。"}, "public_samples": [{"input": "2 4\n", "output": "3.0\n", "explanation": "两个数的平均值。"}], "hidden_tests": [{"input": "2 4\n", "output": "3.0\n"}, {"input": "1\n", "output": "1.0\n"}], "reference_solution": "import sys\nvalues = list(map(float, sys.stdin.read().split()))\nif not values: print(0.0)\nelse: print(sum(values) / len(values))\n", "reference_language": "python", "rubric": ["指出 len(values)-1 的错误", "给出空输入处理", "解释最小复现用例"]},
                ],
            }
            # The demo exposes deterministic alternatives for every supported
            # practical type without turning the default vision fixture into a
            # ten-question plan. These materials are entirely fictional.
            user_lower = user.lower()
            if any(marker in user_lower for marker in ("数据库", "sqlite", "sql")):
                payload["topics"][-2:] = [json.loads(json.dumps(DEMO_PRACTICAL_TASKS["sql"])), json.loads(json.dumps(DEMO_PRACTICAL_TASKS["cpp"]))]
            elif any(marker in user for marker in ("实验结果分析", "日志分析")):
                payload["topics"][-2:] = [json.loads(json.dumps(DEMO_PRACTICAL_TASKS["experiment_analysis"])), json.loads(json.dumps(DEMO_PRACTICAL_TASKS["cpp"]))]
        elif "第一道问题" in user:
            if "严格按照面试计划顺序推进" in system and "主动控制面试节奏" in system:
                question = "请按结论、方法、证据三个部分说明你目标方向中的一个核心问题。"
            elif "优先让候选人完整展开" in system:
                question = "请先完整、具体地介绍一段与你目标方向最相关的经历。"
            else:
                question = "请具体说明你目标方向中的一个核心问题，以及你判断它重要的依据。"
            payload = {"question": question, "topic": "方向基础", "topic_index": 0, "done": False, "clarification": False, "observation": "", "next_action": "next_topic"}
        elif "面试官" in system:
            self.interview_count += 1
            payload = {"question": "请再举一个具体例子说明你的判断。", "topic": "动态追问", "topic_index": None, "done": False, "clarification": False, "observation": "候选人回答已记录，待继续核验具体依据。", "next_action": "follow_up"}
        elif "反馈教练" in system:
            payload = {
                "overall": "候选人能够围绕问题给出基本判断，具备继续训练的基础；本轮对项目细节和实验论证的证据仍然有限。",
                "evidence_coverage": "基于本轮转录和候选人档案，证据覆盖有限。",
                "confidence": "中",
                "dimension_scores": {
                    "专业知识与基础": {"score": 68, "evidence": ["第 1 轮能围绕方向核心概念作出基本说明"], "confidence": "中"},
                    "项目与科研经历深度": {"score": 58, "evidence": ["候选人档案列出项目，但本轮缺少个人贡献和复现实验细节"], "confidence": "低"},
                    "科研思维": {"score": 55, "evidence": ["回答提到指标和对照，但尚未展开因果验证"], "confidence": "低"},
                    "方向匹配": {"score": 70, "evidence": ["候选人档案中的研究兴趣与目标方向相关"], "confidence": "中"},
                    "面试表达与应答": {"score": 72, "evidence": ["第 1 轮能够直接回应问题并继续说明思路"], "confidence": "中"},
                },
                "strengths": ["愿意说明自己的思路", "能够围绕问题继续回答"],
                "professional_knowledge_gaps": [{"category": "科研推理", "statement": "需要补充可验证的对照和指标。", "evidence": ["面试转录"], "action": "用假设—指标—对照三行卡片练习。"}],
                "interview_skill_gaps": [],
                "improvement_examples": ["先给结论，再说明机制、证据和局限。"],
                "priority_drills": ["为一个项目写单变量消融表。", "用三分钟解释一个核心概念并录音复盘。", "每天写一张假设—指标—对照—失败解释卡片。"],
                "next_round": "增加项目结果因果性和失败复盘追问。",
            }
        else:
            payload = {}
        return Completion(content=json.dumps(payload, ensure_ascii=False))
