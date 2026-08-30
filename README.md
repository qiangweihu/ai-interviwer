# AI 模拟面试官

面向计算机专业保研/课题组科研面试的 Codex 原生训练工作流。它把一次练习组织成（规划在后台自动完成）：

```text
资料准备 → 后台定向准备 → 自适应模拟面试 → 证据化反馈 → 再次练习
```

## 快速开始

在 Codex 中打开本仓库，然后：

1. 输入目标课题组或科研方向，并提供一份脱敏的 PDF、DOCX、Markdown 或 TXT 简历；首次使用会自动进入 `$interview-onboarding`。
2. 资料保存后会自动调用 `$interview-planner` 收集方向资料并准备约 25 分钟、8–12 个主问题的内部计划；用户无需单独进入规划阶段，也不会默认看到完整题单。
3. 说“开始面试”，由 `$mock-interviewer` 一次提问一个问题。推荐使用 Codex 的语音转文字输入；随时输入“结束面试”即可提前结束。
4. 结束后由 `$interview-feedback` 输出带回答证据的优势、问题、评分和下一轮训练动作。
5. 说“再练一轮”会创建新的 session，保留历史记录并复用全局档案。

也可以显式调用 `$interview-onboarding`、`$interview-planner`、`$mock-interviewer` 或 `$interview-feedback` 进行调试或重试。阶段状态由根目录 `AGENTS.md` 统一路由，不能跳过缺失资料或过期计划。

## 服务器版（FastAPI + React）

仓库同时包含一个可部署的匿名 Web 版本。它把四个 skill 的规则固化为后端状态机和 MiMo 提示词模块，前端由 FastAPI 同源提供。服务器版不依赖 Codex 窗口，也不需要用户安装 Codex。上传资料后规划自动在后台完成，网页只显示“面试已准备好”，不单独展示规划页面或完整题单。

本地开发（需要 Python 3.12、Node 22）：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
export MOCK_MIMO=true
uvicorn backend.app.main:app --reload --port 8000
```

另开终端构建前端：

```bash
cd frontend
npm install
npm run build
```

浏览器访问 `http://127.0.0.1:8000`，可使用 `demo/fictional-cv.md` 测试完整闭环。生产环境只在服务器 `.env` 配置 `MIMO_API_KEY`，不要提交密钥。默认 `MIMO_WEB_SEARCH_ENABLED=false`；开通 MiMo Web Search Plugin 后再改为 `true`，规划资料才会保存联网引用。

服务器首版目录和手动更新方式：

```text
/opt/ai-interviwer       GitHub 工作副本
/var/lib/ai-interviwer   SQLite 数据卷
/opt/ai-interviwer/.env  600 权限的服务器密钥
```

首次部署先在服务器执行 `cp .env.example .env`，填入真实的 `MIMO_API_KEY` 并执行 `chmod 600 .env`；之后再运行发布脚本。

在服务器上执行 `bash scripts/deploy.sh` 会拉取 `main`、备份 SQLite、重建容器并检查 `/health`。Docker Compose 将服务暴露为 `http://47.242.251.150:8000`。首版是匿名、24 小时自动清理、明文 HTTP，只适合虚构或充分脱敏简历；真实资料需等 HTTPS 版本。

阿里云 Ubuntu 24.04 首次准备（若镜像尚未安装 Docker）：

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin curl
sudo systemctl enable --now docker
git clone https://github.com/qiangweihu/ai-interviwer.git /opt/ai-interviwer
sudo mkdir -p /var/lib/ai-interviwer
sudo chown -R "$USER":"$USER" /opt/ai-interviwer /var/lib/ai-interviwer
cd /opt/ai-interviwer
cp .env.example .env
chmod 600 .env
# 编辑 .env 填写 MIMO_API_KEY
bash scripts/deploy.sh
```

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
├── tests/test_framework.py
├── tests/test_server_contract.py
├── backend/                 # FastAPI、SQLite、MiMo 适配器
├── frontend/                # React/Vite 单页向导
├── Dockerfile
└── docker-compose.yml
```

用户资料和练习产物位于本地 `.interview/`：全局档案在 `profile/`，每次练习在 `sessions/<session-id>/`。`.interview/` 已被 `.gitignore` 忽略；测试和 Demo 只使用虚构数据。

## 设计边界

- MVP 只服务计算机科研/保研课题组面试，不覆盖大厂实习面试。
- Codex 侧仍是 instruction-only skills；服务器侧提供 FastAPI、React、SQLite 和 MiMo API 运行时。
- 服务器首版不做扫描 PDF OCR、音频上传、TTS 或独立 ASR；可使用操作系统/输入法的语音转文字。
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
