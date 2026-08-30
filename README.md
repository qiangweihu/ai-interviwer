# AI 模拟面试官

面向计算机专业保研/课题组科研面试的 Codex 原生训练工作流。它把一次练习组织成（规划在后台自动完成）：

```text
资料准备 → 后台定向准备 → 自适应模拟面试 → 证据化反馈 → 再次练习
```

## 快速开始

在 Codex 中打开本仓库，然后：

1. 输入目标课题组或科研方向，并提供一份脱敏的 PDF、DOCX、Markdown 或 TXT 简历；首次使用会自动进入 `$interview-onboarding`。
2. 资料保存后会自动调用 `$interview-planner`，基于候选人资料和通用知识准备约 35 分钟、7–10 个主项目的混合计划（含 1–2 个实操题）；当前版本不联网检索，用户无需单独进入规划阶段，也不会默认看到完整题单。
3. 说“开始面试”，由 `$mock-interviewer` 一次展示一个问题。实操题支持 Python/C++ 编程、代码理解/调试、SQLite 查询和实验结果分析；服务器版可直接使用网页语音转文字；随时输入“结束面试”即可提前结束。
4. 结束后由 `$interview-feedback` 输出仅基于本轮表现的模拟面试通过概率、带回答证据的总结、优势、专业知识/面试技巧不足和下一轮训练动作。

概率由服务端根据专业知识、项目/科研深度、科研思维、方向匹配和面试表达五类证据按固定权重计算，并按证据覆盖信心收缩；页面只展示这一个概率，不展示分项分数。它用于训练复盘，不等同于最终招生录取率。
5. 说“再练一轮”会创建新的 session，保留历史记录并复用全局档案。

服务器版在每轮自动规划前提供三组面试官风格选择：主导/倾听、严格/和蔼、循规蹈矩/随心所欲。三个维度独立组合；默认是“主导 + 和蔼 + 循规蹈矩”。风格会影响问题措辞、追问预算和主题顺序，但不改变反馈口径。准备完成后本轮风格锁定，下一轮默认沿用并可重新选择。

实操题可以先试跑公开样例（每题最多 10 次），再进行一次最终提交；最终提交会在隔离 runner 中运行隐藏测试并锁定题目。隐藏测试、参考解法和评分 rubric 不会发送到浏览器，代码也不会在主应用或 Codex 工作区直接执行。runner 不可用时会明确提示并停止可执行题，不退化为模型猜测。

也可以显式调用 `$interview-onboarding`、`$interview-planner`、`$mock-interviewer` 或 `$interview-feedback` 进行调试或重试。阶段状态由根目录 `AGENTS.md` 统一路由，不能跳过缺失资料或过期计划。

## 服务器版（FastAPI + React）

仓库同时包含一个可部署的匿名 Web 版本。它把四个 skill 的规则固化为后端状态机和 MiMo 提示词模块，前端由 FastAPI 同源提供。服务器版不依赖 Codex 窗口，也不需要用户安装 Codex。上传资料后规划自动在后台完成，网页只显示“面试已准备好”，不单独展示规划页面或完整题单。

本地开发（需要 Python 3.12、Node 22）：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
export MOCK_MIMO=true
export PRACTICAL_RUNNER_ENABLED=true
uvicorn backend.app.main:app --reload --port 8000
```

另开终端构建前端：

```bash
cd frontend
npm install
npm run build
```

浏览器访问 `http://127.0.0.1:8000`，可使用 `demo/fictional-cv.md` 测试完整闭环。Mock MiMo 默认给出 Python/代码调试题；将虚构方向写成“数据库/SQLite”或“实验结果分析/日志分析”可切换到内置的 SQL、C++20 或实验分析材料。生产环境只需在服务器 `.env` 配置 `MIMO_API_KEY`；语音识别使用服务器本地模型，不需要额外的 ASR API Key。当前版本不进行联网检索，规划资料会明确标注“降级/未联网核验”。

### 语音转文字

面试进行中可以直接录音，服务端使用本地 `faster-whisper` 模型转写，识别结果会先回填到文本框，由候选人检查或修改后再提交给面试官。上传内容通过请求流限制在内存中，不写入 SQLite 或数据卷；默认单段最多 3 分钟、15 MB。

生产环境在 `.env` 中配置：

```dotenv
LOCAL_ASR_ENABLED=true
LOCAL_ASR_MODEL=small
LOCAL_ASR_MODEL_DIR=/var/lib/ai-interviwer/models
LOCAL_ASR_COMPUTE_TYPE=int8
LOCAL_ASR_LANGUAGE=zh
MAX_AUDIO_BYTES=15728640
MAX_AUDIO_SECONDS=180
```

第一次使用某个模型时会下载模型文件并缓存到 `LOCAL_ASR_MODEL_DIR`，之后离线运行；模型下载需要服务器能够访问模型仓库，也可以提前把模型文件放入该目录。`LOCAL_ASR_ENABLED=false` 会关闭语音入口，不影响文字回答。本地 `MOCK_MIMO=true` 时使用固定的虚构转写，不加载模型。

默认 `small` 模型适合中文面试的准确率与 CPU 消耗平衡；内存较小的服务器可以改为 `base`，或把模型目录预先复制到数据卷后再启动服务。

### 实操题 runner

`docker-compose.yml` 会启动仅内网可访问的 `runner` 服务。主应用只通过 `PRACTICAL_RUNNER_URL` 调用它，Docker socket 只挂载给 runner orchestrator。runner 为每次执行创建一次性容器，关闭网络、宿主挂载和 Linux capabilities，并限制 CPU、内存、进程数、输出和时长。生产启用前请设置 `PRACTICAL_RUNNER_ENABLED=true`，并确保 runner 镜像已经构建：

```bash
docker compose build runner app
docker compose up -d
```

Codex 原生 skills 使用 `scripts/practical_runner.py`，该脚本只向 runner 发请求，不提供在当前工作区执行候选人代码的选项。`RUNNER_USE_DOCKER=false` 仅用于本地 runner 单元测试。runner 默认最多并发 2 个一次性任务（`RUNNER_MAX_CONCURRENCY=2`）；队列满或 Docker 不可用时返回明确的 503，不会在应用容器或工作区直接执行候选人代码。

浏览器只允许网页在 HTTPS（或本机 `localhost`）环境调用麦克风。当前公网 IP 的明文 HTTP 页面仍可选择已有录音文件，但要使用“开始语音回答”，必须先给域名配置 HTTPS 反向代理；这也是处理真实简历和真实口语前的必要条件。

服务器首版目录和手动更新方式：

```text
/opt/ai-interviwer       GitHub 工作副本
/var/lib/ai-interviwer   SQLite 数据卷
/opt/ai-interviwer/.env  600 权限的服务器密钥
```

首次部署先在服务器执行 `cp .env.example .env`，填入真实的 `MIMO_API_KEY` 并执行 `chmod 600 .env`；之后再运行发布脚本。

在服务器上执行 `bash scripts/deploy.sh` 会拉取 `main`、备份 SQLite、重建容器并检查 `/health`。Docker Compose 将服务暴露为 `http://47.242.251.150:8000`。匿名会话会在 24 小时后自动清理；明文 HTTP 只适合虚构或充分脱敏资料，也不能直接调用浏览器麦克风。

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
├── runner.Dockerfile
└── docker-compose.yml
```

用户资料和练习产物位于本地 `.interview/`：全局档案在 `profile/`，每次练习在 `sessions/<session-id>/`。`.interview/` 已被 `.gitignore` 忽略；测试和 Demo 只使用虚构数据。

## 设计边界

- MVP 只服务计算机科研/保研课题组面试，不覆盖大厂实习面试。
- Codex 侧仍是 instruction-only skills；服务器侧提供 FastAPI、React、SQLite 和 MiMo API 运行时。
- 服务器支持本地 faster-whisper ASR 和录音文件上传，但不保存音频；暂不做扫描 PDF OCR 或 TTS。
- 首版实操不提供完整终端、多文件工程、联网依赖安装、GPU、JavaScript/Java/Shell 或 Notebook；代码运行只接受 Python 3.12、C++20，SQL 运行于一次性只读 SQLite。
- 规划资料只使用候选人资料和通用知识，不联网检索，并显式标注未核验范围。
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
