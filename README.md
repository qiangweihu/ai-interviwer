# AI 模拟面试官

面向计算机专业保研/课题组科研面试的 Codex 原生训练工作流。它把一次练习组织成：

```text
资料准备 → 定向规划 → 自适应模拟面试 → 证据化反馈 → 再次练习
```

## 快速开始

在 Codex 中打开本仓库，然后：

1. 输入目标课题组或科研方向，并提供一份脱敏的 PDF、DOCX、Markdown 或 TXT 简历；首次使用会自动进入 `$interview-onboarding`。
2. 说“规划一次科研面试”，由 `$interview-planner` 收集方向资料并生成约 25 分钟、8–12 个主问题的计划。
3. 说“开始面试”，由 `$mock-interviewer` 一次提问一个问题。推荐使用 Codex 的语音转文字输入；随时输入“结束面试”即可提前结束。
4. 结束后由 `$interview-feedback` 输出带回答证据的优势、问题、评分和下一轮训练动作。
5. 说“再练一轮”会创建新的 session，保留历史记录并复用全局档案。

也可以显式调用 `$interview-onboarding`、`$interview-planner`、`$mock-interviewer` 或 `$interview-feedback`。阶段状态由根目录 `AGENTS.md` 统一路由，不能跳过缺失资料或过期计划。

## 仓库结构

```text
├── .agents/skills/
│   ├── interview-onboarding/
│   ├── interview-planner/
│   ├── mock-interviewer/
│   └── interview-feedback/
├── demo/
│   ├── fictional-cv.md
│   ├── fictional-research-brief.md
│   ├── fictional-interview-plan.md
│   └── fictional-feedback.md
└── tests/test_framework.py
```

用户资料和练习产物位于本地 `.interview/`：全局档案在 `profile/`，每次练习在 `sessions/<session-id>/`。`.interview/` 已被 `.gitignore` 忽略；测试和 Demo 只使用虚构数据。

## 设计边界

- MVP 只服务计算机科研/保研课题组面试，不覆盖大厂实习面试。
- 首版是 instruction-only skills，不包含独立 Web 前后端、数据库、TTS、ASR 或模型 API。
- 规划资料记录来源 URL、访问日期和结论；外部资料不可用时会显式降级。
- 面试官在面试过程中不公布评分、不教学、不提前纠正答案；反馈集中在结束后。
- 语音输入只是交互建议，不保存音频，也不会因口头语或明显的 ASR 噪声直接扣分。

## 校验

运行标准库测试检查 skills、metadata、路由规则、隐私忽略和虚构 Demo 是否完整：

```bash
python3 -m unittest discover -s tests -v
```

如需校验单个 skill 的 frontmatter，也可运行 Codex 随附的 `skill-creator/scripts/quick_validate.py`。

## 隐私

测试时只使用脱敏简历或虚构数据。请不要提交真实姓名、联系方式、证件、API key 或真实面试记录；`.interview/` 已默认不会被 Git 跟踪。
