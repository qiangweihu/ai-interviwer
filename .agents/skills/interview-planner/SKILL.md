---
name: interview-planner
description: 基于研究方向资料和候选人简历，规划计算机科研/保研面试的主题、问题、追问与评价证据。
metadata:
  short-description: 生成定向科研面试计划
---

# 科研面试内容规划

## 何时使用

当 `.interview/profile/` 档案完整且需要为当前 session 设计面试时使用。若缺少方向或简历，先调用 `$interview-onboarding`；不要把本 skill 用于通用知识问答或泛化的实习面试题库。

## 前置检查

1. 读取根目录 `AGENTS.md`、`.interview/state.md`、`research-context.md` 和 `candidate-profile.md`。
2. 若状态不是 `ready_for_planning`，或用户要求重新规划，先确认当前 session；创建新 session 时使用新的 `YYYYMMDD-HHMMSS-方向-slug`，绝不覆盖已有目录。
3. 确认 `profile_revision`，最终把同一数值写入 `plan_profile_revision`，供面试官阻止使用过期计划。

## 研究与规划工作流

1. 围绕具体方向整理少量高信号的通用基础知识，只使用候选人资料和模型已有知识；当前版本不联网检索，也不调用浏览器或外部资料工具。
2. 在 `.interview/sessions/<session-id>/research-brief.md` 记录 `research_status: degraded`、通用结论、未核验范围及其与候选人简历/面试主题的关联；不生成或猜测 URL、论文来源和课题组近期事实。
3. 生成约 35 分钟、7–10 个主项目的 `.interview/sessions/<session-id>/interview-plan.md`；默认包含 6–8 个口头问题和 1–2 个实操题。主线必须覆盖：
   旧版仅口头计划仍可保留 8–12 个主题并继续运行，新版混合计划采用上述题量契约。
   - 方向相关的专业基础；
   - 简历项目和科研经历深挖；
   - 科研问题拆解、实验设计与结果解释；
   - 与目标方向/课题组的匹配及研究动机；
   - 沟通、反思和开放问题。
4. 实操题首版支持 `coding`（Python/C++ 标准输入输出）、`code_review`（代码解释/调试，可选修正版）和 `practical`（SQLite 查询或实验结果分析）。每个主题写明：考察目标、核心问题、1–3 个候选追问、预期证据、评价维度和建议时间。问题要结合简历中的真实项目，不能凭空制造经历。
5. 对可执行题额外记录语言、初始代码/材料、公开样例、隐藏测试、参考解法和 rubric；测试只能是输入/输出数据，不能生成会被执行的 shell 或测试脚本。计划交付前通过统一 `scripts/practical_runner.py`/隔离 runner 运行参考解法，失败则修复或重生成，不能交付未验证题目。
6. 计划采用“主线固定、追问动态”：核心主题都要覆盖，但面试官可根据回答选择追问、跳过已充分证明的内容或降低重复度。不要把完整题单预先作为对话首屏展示。
7. 由于本版本不进行外部研究，所有研究摘要都必须写明 `research_status: degraded`、未核验范围和可能影响；不能把通用知识写成课题组事实。
8. 更新 `state.md`：`status: ready_for_interview`、`current_session`、`plan_profile_revision` 和 `updated_at`。规划默认作为面试开始前的后台准备动作；只向用户确认面试已准备好，不展示完整题单或逐题问题。只有用户明确要求时，才提供不泄露核心问题的简短摘要。

## 产物契约

必须生成：

- `.interview/sessions/<session-id>/research-brief.md`
- `.interview/sessions/<session-id>/interview-plan.md`
- 实操提交的摘要可追加到 `.interview/sessions/<session-id>/practical-submissions.md`；隐藏测试和参考解法不得写入可展示产物。
- `.interview/state.md`

如果档案发生变化，旧 session 的计划只读保留并标记过期；不得静默复用。
