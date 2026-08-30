---
name: interview-onboarding
description: 收集并整理计算机科研面试的目标课题组/研究方向与脱敏简历，建立供其他面试 skills 共享的本地候选人档案。
metadata:
  short-description: 建立科研面试全局档案
---

# 科研面试资料准备

## 何时使用

当用户第一次开始科研面试、缺少研究方向或简历、或明确要求更新其中任一项时使用。不要把普通简历润色、求职信写作或大厂行为面试当作本 skill 的目标。

## 输入

- 具体课题组、实验室或科研方向；如果用户只给出宽泛的“人工智能”，追问到可检索的子方向、目标导师/课题组或代表性问题。
- 脱敏的 PDF、DOCX、Markdown 或 TXT 简历。若文件不可读，说明原因并请求可读版本，不要猜测内容。

## 工作流

1. 读取根目录 `AGENTS.md` 和现有 `.interview/state.md`。保留旧 session，不覆盖历史档案。
2. 确认用户希望使用的简历版本；只处理用户明确提供或指定的文件。PDF/DOCX 使用可用的文档读取能力提取文本，保留项目名、时间、角色、方法、结果和原文证据。
3. 将研究方向写入 `.interview/profile/research-context.md`，至少包括：
   - `direction`、`target_group`、`target_program`（未知则写“待确认”）；
   - 用户明确的面试目标和已知重点；
   - 术语、边界和待核实问题；
   - `source_type: user-provided` 与更新时间。
4. 将简历事实写入 `.interview/profile/candidate-profile.md`，按教育背景、课程基础、项目、科研、技能/工具、成果、兴趣和潜在追问点组织。每个重要事实尽量保留简历中的原句或页码/段落定位；无法确认的内容标记为“待确认”。
5. 不补写简历没有的论文、指标、职责、熟练程度或研究结论。敏感信息只保留完成面试所需的最小内容，联系方式默认丢弃。
6. 创建新的 `profile_revision`（从 1 开始递增），更新 `.interview/state.md`：状态设为 `ready_for_planning`，清空 `plan_profile_revision`，并记录更新时间。若用户只提供了部分资料，状态设为 `needs_onboarding` 并列出缺失项。
7. 用简短摘要向用户确认已记录的方向、简历要点和下一步；不要在确认消息中复述不必要的个人敏感信息。

## 产物契约

必须生成或更新：

- `.interview/profile/research-context.md`
- `.interview/profile/candidate-profile.md`
- `.interview/state.md`

不得生成真实资料的副本到仓库跟踪目录，也不得自动联网搜索研究内容；联网研究由 `$interview-planner` 负责。
