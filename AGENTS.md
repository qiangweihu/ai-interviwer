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
        ├── practical-submissions.md
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
2. 若档案完整但当前 session 缺少有效的 `research-brief.md` 或 `interview-plan.md`，在后台调用 `$interview-planner`。规划是面试开始前的内部准备动作，不要求用户单独进入或确认规划阶段，也不默认展示完整题单。
3. 若计划有效且状态为 `ready_for_interview` 或 `interview_in_progress`，调用 `$mock-interviewer`。
4. 若状态为 `ready_for_feedback` 且存在完整 `transcript.md`，调用 `$interview-feedback`。
5. 完成反馈后保持 `complete`，用户说“再练一轮/开始下一次”时创建新 session；不要删除历史记录。

用户可以显式使用 `$interview-onboarding`、`$interview-planner`、`$mock-interviewer` 或 `$interview-feedback`。显式调用也必须遵守前置状态检查，不能跳过缺失的全局档案或过期计划。

规划完成后只需向用户确认“面试已准备好”，并进入模拟面试；只有用户明确要求时才展示规划摘要，不能在首屏泄露完整问题。

## 统一隐私与证据规则

- 只接受脱敏或虚构简历；不要把简历、联系方式、回答或反馈复制到 Git 跟踪文件。
- 不把简历中没有的经历、论文、指标或技能当作事实；不确定内容标记为“待确认”。
- 反馈必须能回指到简历或 `transcript.md` 的具体证据；可以给出仅基于本轮面试表现的模拟面试通过概率，但必须明确它不等同于最终招生录取率，不能据此做录取、淘汰等确定性判断。
- 面试默认约 35 分钟、7–10 个主项目，其中 6–8 个口头问题、1–2 个实操题；实操题可为 Python/C++ 编程、代码理解/调试、SQLite 查询或实验结果分析。语音转文字由 Codex 客户端提供，所有文字输入都视为候选人的口语转写。
- 面试研究资料只使用用户提供的内容和通用知识；当前版本不联网检索，研究摘要必须明确标注降级/未核验状态，不生成外部来源。

## 默认语言与交互

默认使用简体中文，跟随用户主动使用的语言。除非用户要求，否则不构建独立 Web 服务、不调用外部模型 API、不保存音频；本阶段的价值来自可复用的 skills、结构化证据和连续练习。

## 服务器运行时

仓库同时包含 `backend/` 和 `frontend/` 的服务器版实现。服务器运行时把本文件和四个 skills 当作产品规则来源，但不依赖 Codex skill 自动发现；用户资料必须写入服务器 SQLite 数据卷，不得写入 Git 跟踪文件。

- 本地开发可使用 `MOCK_MIMO=true` 跑虚构数据；生产只通过环境变量提供 `MIMO_API_KEY`。
- 默认部署为 Docker Compose 应用容器加内网 runner 容器，应用监听 8000；服务器代码位于 `/opt/ai-interviwer`，运行数据位于 `/var/lib/ai-interviwer`。
- 服务器每轮面试在自动规划前选择面试官风格的三个维度（主导/倾听、严格/和蔼、循规/随心）；服务端将其解析为固定 Prompt 与题序/追问策略，规划完成后锁定为本轮快照，反馈口径不变。
- 实操题的题面、公开样例和候选人当前提交可以展示；隐藏测试、参考解法和评分 rubric 只能留在服务器/隔离 runner。代码只能通过 runner 执行，不能在主应用或 Codex 工作区直接运行；runner 不可用时记录“未执行”并暂停可执行题。
- 公开试跑最多 10 次，最终提交后题目锁定；最终提交的源码、解释和测试摘要写入当前 session 的证据文件，公开试跑源码不持久化。
- 正式更新先在本地测试并推送 GitHub，再通过 `scripts/deploy.sh` SSH 发布；不要在服务器工作副本直接编辑业务代码。
