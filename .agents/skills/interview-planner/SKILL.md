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

1. 围绕具体方向检索少量高信号资料：目标实验室/导师官网、代表性论文、课程讲义或教材、权威技术文档。使用可用的浏览器或资料读取工具；不把搜索结果原样堆入输出。
2. 在 `.interview/sessions/<session-id>/research-brief.md` 记录每个采用的来源：标题、机构/作者、URL、访问日期、关键结论，以及它与候选人简历或面试主题的关联。无法访问或无法核验的内容标记为 `unverified`。
3. 生成约 25 分钟、8–12 个主问题的 `.interview/sessions/<session-id>/interview-plan.md`。主线必须覆盖：
   - 方向相关的专业基础；
   - 简历项目和科研经历深挖；
   - 科研问题拆解、实验设计与结果解释；
   - 与目标方向/课题组的匹配及研究动机；
   - 沟通、反思和开放问题。
4. 每个主题写明：考察目标、核心问题、1–3 个候选追问、预期证据、评价维度和建议时间。问题要结合简历中的真实项目，不能凭空制造经历。
5. 计划采用“主线固定、追问动态”：核心主题都要覆盖，但面试官可根据回答选择追问、跳过已充分证明的内容或降低重复度。不要把完整题单预先作为对话首屏展示。
6. 若外部研究不可用，仍可基于通用知识生成计划，但在 `research-brief.md` 顶部写明 `research_status: degraded`、未核验范围和可能影响；不能把推测写成课题组事实。
7. 更新 `state.md`：`status: ready_for_interview`、`current_session`、`plan_profile_revision` 和 `updated_at`。向用户展示计划摘要、覆盖维度和预计时长，保留具体问题供面试流程使用。

## 产物契约

必须生成：

- `.interview/sessions/<session-id>/research-brief.md`
- `.interview/sessions/<session-id>/interview-plan.md`
- `.interview/state.md`

如果档案发生变化，旧 session 的计划只读保留并标记过期；不得静默复用。
