# AI 科研模拟面试官

本仓库是一个面向计算机专业保研/课题组科研面试的 Codex 原生工作流。稳定的编排规则放在这里；任何用户的研究方向、简历、回答和反馈都只能写入 `.interview/`，不得写入本文件。

## 工作区与阶段状态

所有 skill 共享当前仓库下的 `.interview/` 工作区。该目录已加入 `.gitignore`，其结构和状态约定如下：

```text
.interview/
├── profile/
│   ├── research-context.md
│   └── candidate-profile.md
├── state.md
└── sessions/
    └── <session-id>/
        ├── research-brief.md
        ├── interview-plan.md
        ├── transcript.md
        ├── observations.md
        └── feedback.md
```

`state.md` 至少包含：`status`、`current_session`、`profile_revision`、`plan_profile_revision` 和 `updated_at`。允许的 `status` 为：

- `needs_onboarding`：缺少研究方向或简历；
- `ready_for_planning`：全局档案完整，需要生成本次计划；
- `ready_for_interview`：本次计划已生成且仍匹配当前档案；
- `interview_in_progress`：正在逐轮记录回答；
- `ready_for_feedback`：面试已结束，等待反馈；
- `complete`：本次反馈已生成。

创建新练习时使用新的时间戳 slug 作为 `<session-id>`，不能覆盖已有 session。用户更新研究方向或简历时递增 `profile_revision`，并将旧计划标记为过期，重新进入 `ready_for_planning`。

## 路由规则

1. 若 `.interview/profile/research-context.md` 或 `candidate-profile.md` 缺失、不完整或用户明确要更新资料，调用 `$interview-onboarding`。
2. 若档案完整但当前 session 缺少有效的 `research-brief.md` 或 `interview-plan.md`，调用 `$interview-planner`。
3. 若计划有效且状态为 `ready_for_interview` 或 `interview_in_progress`，调用 `$mock-interviewer`。
4. 若状态为 `ready_for_feedback` 且存在完整 `transcript.md`，调用 `$interview-feedback`。
5. 完成反馈后保持 `complete`，用户说“再练一轮/开始下一次”时创建新 session；不要删除历史记录。

用户可以显式使用 `$interview-onboarding`、`$interview-planner`、`$mock-interviewer` 或 `$interview-feedback`。显式调用也必须遵守前置状态检查，不能跳过缺失的全局档案或过期计划。

## 统一隐私与证据规则

- 只接受脱敏或虚构简历；不要把简历、联系方式、回答或反馈复制到 Git 跟踪文件。
- 不把简历中没有的经历、论文、指标或技能当作事实；不确定内容标记为“待确认”。
- 反馈必须能回指到简历或 `transcript.md` 的具体证据；不能据此做录取、淘汰等确定性判断。
- 面试默认约 25 分钟、8–12 个主问题；语音转文字由 Codex 客户端提供，所有文字输入都视为候选人的口语转写。
- 面试研究资料的外部来源只作为本地 session 参考，记录 URL、访问日期和结论；资料不可用时明确标注降级状态。

## 默认语言与交互

默认使用简体中文，跟随用户主动使用的语言。除非用户要求，否则不构建独立 Web 服务、不调用外部模型 API、不保存音频；本阶段的价值来自可复用的 skills、结构化证据和连续练习。
