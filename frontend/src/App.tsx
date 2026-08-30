import { FormEvent, useEffect, useMemo, useState } from "react";
import VoiceRecorder from "./VoiceRecorder";

type Status =
  | "needs_onboarding"
  | "ready_for_planning"
  | "ready_for_interview"
  | "interview_in_progress"
  | "ready_for_feedback"
  | "complete";

type StyleSelection = {
  initiative: "leading" | "listening";
  tone: "strict" | "friendly";
  structure: "structured" | "adaptive";
};

type StyleDimension = {
  label: string;
  options: { value: string; label: string; description: string }[];
};

type StyleCatalog = {
  version: string;
  default_selection: StyleSelection;
  dimensions: Record<keyof StyleSelection, StyleDimension>;
};

type PublicStyle = StyleSelection & {
  version: string;
  preset_id?: string;
  control?: "dominant" | "listener";
  plan_adherence?: "structured" | "flexible";
  name: string;
  summary: string;
  traits: string[];
};

type Session = {
  status: Status;
  profile_revision: number;
  plan_profile_revision?: number;
  current_run_id?: string;
  expires_at: string;
  profile_complete: boolean;
  plan_preview?: {
    duration_minutes: number;
    main_question_count: number;
    research_status?: string;
    topics: { title: string; objective: string; minutes: number; type?: string }[];
  };
  interviewer_style?: PublicStyle;
};

type Task = {
  id: string;
  type: "oral" | "coding" | "code_review" | "practical";
  practical_type?: "sql" | "experiment_analysis";
  title: string;
  objective: string;
  core_question: string;
  minutes: number;
  constraints?: string[];
  language_options: string[];
  starter_code?: string;
  materials?: Record<string, unknown>;
  public_samples?: { input: string; output: string; explanation?: string; rows?: unknown[][] }[];
  locked?: boolean;
  submission?: { language?: string; locked: boolean; result?: { status?: string; passed?: number; total?: number; compile_error?: string; runtime_error?: string; output_truncated?: boolean; execution_ms?: number } };
};

type Turn = {
  role: "interviewer" | "candidate";
  content: string;
  turn_kind?: string;
  task_id?: string;
  submission?: { source?: string; language?: string; result?: { passed?: number; total?: number; status?: string } };
};

type Feedback = {
  feedback_version: "2";
  interview_pass_probability: number;
  overall: string;
  evidence_coverage: string;
  confidence: string;
  strengths: string[];
  professional_knowledge_gaps: { category: string; statement: string; evidence: string[]; action: string }[];
  interview_skill_gaps: { category: string; statement: string; evidence: string[]; action: string }[];
  improvement_examples: string[];
  priority_drills: string[];
  next_round: string;
};

const STYLE_KEYS: (keyof StyleSelection)[] = ["initiative", "tone", "structure"];
const DEFAULT_STYLE: StyleSelection = {
  initiative: "leading",
  tone: "friendly",
  structure: "structured",
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "include", ...init });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "请求失败，请稍后重试");
  return body as T;
}

// randomUUID() is only exposed by some browsers in secure contexts. The
// server uses this value only for answer idempotency, so keep a compatible
// fallback for the HTTP/IP deployment and older Safari versions.
function createRequestId(): string {
  const webCrypto = typeof globalThis.crypto !== "undefined" ? globalThis.crypto : undefined;
  if (webCrypto && typeof webCrypto.randomUUID === "function") return webCrypto.randomUUID();
  if (webCrypto && typeof webCrypto.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    webCrypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0"));
    return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}

function selectionFromStyle(style?: PublicStyle | null): StyleSelection {
  if (!style) return DEFAULT_STYLE;
  return {
    initiative: style.initiative || (style.control === "listener" ? "listening" : "leading"),
    tone: style.tone || "friendly",
    structure: style.structure || (style.plan_adherence === "flexible" ? "adaptive" : "structured"),
  };
}

function StylePicker({
  catalog,
  value,
  onChange,
  disabled = false,
}: {
  catalog: StyleCatalog;
  value: StyleSelection;
  onChange: (next: StyleSelection) => void;
  disabled?: boolean;
}) {
  const selectedLabels = STYLE_KEYS.map((key) => {
    const option = catalog.dimensions[key].options.find((item) => item.value === value[key]);
    return option?.label || value[key];
  });

  return (
    <div className="style-picker">
      <div className="style-axes">
        {STYLE_KEYS.map((key) => {
          const dimension = catalog.dimensions[key];
          return (
            <fieldset key={key} disabled={disabled}>
              <legend>{dimension.label}</legend>
              <div className="style-options">
                {dimension.options.map((option) => (
                  <label className="style-option" key={option.value}>
                    <input
                      type="radio"
                      name={`style-${key}`}
                      checked={value[key] === option.value}
                      onChange={() => onChange({ ...value, [key]: option.value } as StyleSelection)}
                    />
                    <span>
                      <strong>{option.label}</strong>
                      <small>{option.description}</small>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
          );
        })}
      </div>
      <div className="style-preview">
        <div>
          <span className="eyebrow">当前组合</span>
          <p>{selectedLabels.join(" · ")}</p>
        </div>
        <small>风格只改变提问方式、追问和题序，不改变反馈口径。</small>
      </div>
    </div>
  );
}

function StyleBadge({ style }: { style?: PublicStyle }) {
  if (!style) return null;
  return <span className="style-badge" title={style.summary}>{style.name}</span>;
}

function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [styleCatalog, setStyleCatalog] = useState<StyleCatalog | null>(null);
  const [styleSelection, setStyleSelection] = useState<StyleSelection>(DEFAULT_STYLE);
  const [showNextStyle, setShowNextStyle] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [direction, setDirection] = useState("");
  const [group, setGroup] = useState("");
  const [program, setProgram] = useState("");
  const [resume, setResume] = useState<File | null>(null);
  const [question, setQuestion] = useState("");
  const [topic, setTopic] = useState("");
  const [task, setTask] = useState<Task | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [answer, setAnswer] = useState("");
  const [taskSource, setTaskSource] = useState("");
  const [taskExplanation, setTaskExplanation] = useState("");
  const [analysisJudgment, setAnalysisJudgment] = useState("");
  const [analysisEvidence, setAnalysisEvidence] = useState("");
  const [analysisNextValidation, setAnalysisNextValidation] = useState("");
  const [taskLanguage, setTaskLanguage] = useState("python");
  const [taskResult, setTaskResult] = useState<{ status?: string; passed?: number; total?: number; compile_error?: string; runtime_error?: string; output_truncated?: boolean } | null>(null);
  const [taskSeconds, setTaskSeconds] = useState(0);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [paused, setPaused] = useState(false);

  const fail = (reason: unknown) => setError(reason instanceof Error ? reason.message : "请求失败，请稍后重试");
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (reason) {
      fail(reason);
    } finally {
      setBusy(false);
    }
  };

  const taskKey = task ? `${task.id}:${task.type}` : "";
  const draftKey = (id: string) => `interview-draft:${session?.current_run_id || "current"}:${id}`;
  const isAnalysisTask = task?.type === "practical" && task.practical_type === "experiment_analysis";
  useEffect(() => {
    if (!task || task.type === "oral") return;
    const seconds = Math.max(1, (task.minutes || 8) * 60);
    setTaskSeconds(seconds);
    const savedDraft = window.localStorage.getItem(draftKey(task.id));
    if (task.type === "practical" && task.practical_type === "experiment_analysis") {
      try {
        const saved = savedDraft ? JSON.parse(savedDraft) : {};
        setAnalysisJudgment(typeof saved.judgment === "string" ? saved.judgment : "");
        setAnalysisEvidence(typeof saved.evidence === "string" ? saved.evidence : "");
        setAnalysisNextValidation(typeof saved.next_validation === "string" ? saved.next_validation : "");
        setTaskExplanation(typeof saved.explanation === "string" ? saved.explanation : "");
      } catch {
        setAnalysisJudgment("");
        setAnalysisEvidence("");
        setAnalysisNextValidation("");
        setTaskExplanation("");
      }
      setTaskSource("");
    } else {
      let source = savedDraft ?? (task.starter_code || "");
      let explanation = "";
      if (savedDraft) {
        try {
          const saved = JSON.parse(savedDraft);
          if (saved && typeof saved === "object") {
            if (typeof saved.source === "string") source = saved.source;
            if (typeof saved.explanation === "string") explanation = saved.explanation;
          }
        } catch {
          // Keep compatibility with the previous plain-source draft format.
        }
      }
      setTaskSource(source);
      setAnalysisJudgment("");
      setAnalysisEvidence("");
      setAnalysisNextValidation("");
      setTaskExplanation(explanation);
    }
    setTaskResult(task.submission?.result || null);
    setTaskLanguage(task.language_options?.[0] || (task.type === "practical" && task.practical_type === "experiment_analysis" ? "text" : "python"));
  }, [taskKey]);

  useEffect(() => {
    if (!task || task.type === "oral") return;
    const draft = isAnalysisTask
      ? JSON.stringify({ judgment: analysisJudgment, evidence: analysisEvidence, next_validation: analysisNextValidation, explanation: taskExplanation })
      : JSON.stringify({ source: taskSource, explanation: taskExplanation });
    window.localStorage.setItem(draftKey(task.id), draft);
  }, [task, taskSource, isAnalysisTask, analysisJudgment, analysisEvidence, analysisNextValidation]);

  useEffect(() => {
    if (!task || task.type === "oral" || paused || taskSeconds <= 0) return;
    const timer = window.setInterval(() => setTaskSeconds((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [task, paused, taskSeconds > 0]);

  const formatSeconds = (value: number) => `${Math.floor(value / 60).toString().padStart(2, "0")}:${(value % 60).toString().padStart(2, "0")}`;

  const practicalPayload = () => {
    if (isAnalysisTask) {
      return {
        source: "",
        analysis: {
          judgment: analysisJudgment.trim(),
          evidence: analysisEvidence.trim(),
          next_validation: analysisNextValidation.trim(),
        },
        explanation: taskExplanation.trim(),
      };
    }
    return { source: taskSource.trim(), explanation: taskExplanation.trim() };
  };

  const practicalReady = isAnalysisTask
    ? Boolean(analysisJudgment.trim() && analysisEvidence.trim() && analysisNextValidation.trim())
    : task?.type === "code_review"
      ? Boolean(taskSource.trim() || taskExplanation.trim())
      : Boolean(taskSource.trim());

  // A code-review explanation can be submitted without a patch, but public
  // execution only makes sense when a replacement source is present.
  const practicalCanRun = Boolean(
    practicalReady && (!task || task.type !== "code_review" || taskSource.trim())
  );

  // Planning is an internal preparation step. The style is submitted with
  // the plan request, then the server locks its snapshot for this run.
  const preparePlan = async (selection = styleSelection) => {
    const next = await api<Session>("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ interviewer_style: selection }),
    });
    setSession(next);
    setStyleSelection(selectionFromStyle(next.interviewer_style));
  };

  const refresh = async () => {
    let current: Session;
    try {
      current = await api<Session>("/api/session");
    } catch {
      const created = await api<Session>("/api/session", { method: "POST" });
      setSession(created);
      setStyleSelection(selectionFromStyle(created.interviewer_style));
      return;
    }

    setSession(current);
    setStyleSelection(selectionFromStyle(current.interviewer_style));
    if (current.status === "ready_for_planning") {
      setBusy(true);
      setError("");
      try {
        await preparePlan(selectionFromStyle(current.interviewer_style));
      } catch (reason) {
        fail(reason);
      } finally {
        setBusy(false);
      }
      return;
    }

    try {
      if (current.status === "interview_in_progress") {
        const state = await api<{ question?: string; topic?: string; turns: Turn[]; task?: Task }>("/api/interview");
        setQuestion(state.question || "");
        setTopic(state.topic || "");
        setTurns(state.turns || []);
        setTask(state.task || null);
      }
      if (current.status === "complete" && current.current_run_id) {
        const result = await api<{ feedback: Feedback }>("/api/feedback");
        setFeedback(result.feedback);
      }
    } catch (reason) {
      fail(reason);
    }
  };

  useEffect(() => {
    void (async () => {
      try {
        const catalog = await api<StyleCatalog>("/api/interviewer-styles");
        setStyleCatalog(catalog);
        setStyleSelection(catalog.default_selection || DEFAULT_STYLE);
        await refresh();
      } catch (reason) {
        fail(reason);
      }
    })();
  }, []);

  const submitProfile = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      if (!resume) throw new Error("请选择简历文件");
      const form = new FormData();
      form.append("direction", direction);
      form.append("target_group", group);
      form.append("target_program", program);
      form.append("resume", resume);
      const next = await api<Session>("/api/profile", { method: "POST", body: form });
      setSession(next);
      await preparePlan(styleSelection);
    });
  };

  const start = () => void run(async () => {
    const result = await api<{ question: string; topic?: string; task?: Task }>("/api/interview/start", { method: "POST" });
    setQuestion(result.question);
    setTopic(result.topic || "");
    setTask(result.task || null);
    setTurns([]);
    setPaused(false);
    setSession((old) => old ? { ...old, status: "interview_in_progress" } : old);
  });

  const submitAnswer = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      const text = answer.trim();
      if (!text) return;
      const requestId = createRequestId();
      setTurns((old) => [...old, { role: "candidate", content: text }]);
      const result = await api<{ question?: string; topic?: string; done: boolean; task?: Task }>("/api/interview/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Request-ID": requestId },
        body: JSON.stringify({ answer: text, request_id: requestId }),
      });
      setAnswer("");
      if (result.done) {
        setQuestion("");
        setTask(null);
        setSession((old) => old ? { ...old, status: "ready_for_feedback" } : old);
      } else {
        setTurns((old) => [...old, { role: "interviewer", content: result.question || "" }]);
        setQuestion(result.question || "");
        setTopic(result.topic || "");
        setTask(result.task || null);
      }
    });
  };

  const runPublicTask = () => void run(async () => {
    if (!task || task.type === "oral") return;
    if (!practicalCanRun) throw new Error(isAnalysisTask ? "请完整填写判断、依据和下一步验证方案" : "请先填写可执行代码或 SQL");
    const result = await api<{ status: string; passed: number; total: number; compile_error?: string; runtime_error?: string; output_truncated?: boolean }>(`/api/interview/tasks/${encodeURIComponent(task.id)}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request_id: createRequestId(), language: taskLanguage, ...practicalPayload() }),
    });
    setTaskResult(result);
  });

  const submitPracticalTask = () => void run(async () => {
    if (!task || task.type === "oral") return;
    if (!practicalReady) throw new Error(isAnalysisTask ? "请完整填写判断、依据和下一步验证方案" : "请先填写代码或 SQL");
    const result = await api<{ question?: string; topic?: string; done: boolean; task?: Task; result: { status: string; passed: number; total: number; compile_error?: string; runtime_error?: string } }>(`/api/interview/tasks/${encodeURIComponent(task.id)}/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request_id: createRequestId(), language: taskLanguage, ...practicalPayload() }),
    });
    setTaskResult(result.result);
    setTurns((old) => [...old, { role: "candidate", content: `实操题提交：通过 ${result.result.passed}/${result.result.total}`, turn_kind: task.type, task_id: task.id }]);
    if (result.done) {
      setQuestion("");
      setTask(null);
      setSession((old) => old ? { ...old, status: "ready_for_feedback" } : old);
    } else {
      if (result.question) setTurns((old) => [...old, { role: "interviewer", content: result.question || "", turn_kind: result.task?.type, task_id: result.task?.id }]);
      setQuestion(result.question || "");
      setTopic(result.topic || "");
      setTask(result.task || null);
    }
  });

  const finish = () => void run(async () => {
    await api("/api/interview/end", { method: "POST" });
    setQuestion("");
    setTask(null);
    setSession((old) => old ? { ...old, status: "ready_for_feedback" } : old);
  });

  const makeFeedback = () => void run(async () => {
    const result = await api<{ feedback: Feedback }>("/api/feedback", { method: "POST" });
    setFeedback(result.feedback);
    setSession((old) => old ? { ...old, status: "complete" } : old);
  });

  const confirmNextRound = (selection: StyleSelection) => void run(async () => {
    const next = await api<Session>("/api/session/new", { method: "POST" });
    setSession(next);
    setFeedback(null);
    setTurns([]);
    setQuestion("");
    setTask(null);
    setShowNextStyle(false);
    await preparePlan(selection);
  });

  const step = useMemo(() => {
    if (!session) return 0;
    if (session.status === "needs_onboarding" || session.status === "ready_for_planning") return 0;
    if (session.status === "ready_for_interview" || session.status === "interview_in_progress") return 1;
    return 2;
  }, [session]);

  if (!session || !styleCatalog) return <main className="shell"><p>正在建立匿名会话…</p></main>;

  return (
    <main className="shell">
      <header>
        <div>
          <p className="eyebrow">AI RESEARCH INTERVIEW COACH</p>
          <h1>科研模拟面试官</h1>
          <p className="lead">把简历事实转成一轮可练习、可复盘的课题组面试。</p>
        </div>
        <span className="privacy">匿名 · 24 小时自动清理</span>
      </header>

      <nav className="steps">
        {["资料", "面试", "反馈"].map((label, index) => (
          <span className={index <= step ? "active" : ""} key={label}><b>{index + 1}</b>{label}</span>
        ))}
      </nav>

      {error && <div className="error" role="alert">{error}</div>}

      {session.status === "needs_onboarding" && (
        <section className="card">
          <h2>先建立你的面试档案</h2>
          <p className="muted">只上传脱敏或虚构简历。服务器解析后会立即删除原文件。</p>
          <form onSubmit={submitProfile} className="form">
            <label>目标科研方向<input value={direction} onChange={(event) => setDirection(event.target.value)} placeholder="例如：视觉表征学习与跨模态检索" required /></label>
            <label>目标课题组 / 导师<input value={group} onChange={(event) => setGroup(event.target.value)} placeholder="可选，未知时留空" /></label>
            <label>项目或招生方向<input value={program} onChange={(event) => setProgram(event.target.value)} placeholder="可选" /></label>
            <label className="upload">简历文件<input type="file" accept=".pdf,.docx,.md,.markdown,.txt" onChange={(event) => setResume(event.target.files?.[0] || null)} required /><small>{resume ? resume.name : "PDF / DOCX / Markdown / TXT，最大 10 MB"}</small></label>
            <div className="style-section">
              <h3>选择面试官风格</h3>
              <p className="muted">三个维度独立选择，组合会影响提问节奏、语气和题序。</p>
              <StylePicker catalog={styleCatalog} value={styleSelection} onChange={setStyleSelection} disabled={busy} />
            </div>
            <button disabled={busy}>{busy ? "正在准备面试…" : "保存资料并准备面试"}</button>
          </form>
        </section>
      )}

      {session.status === "ready_for_planning" && (
        <section className="card">
          <h2>{busy ? "正在准备面试" : "面试准备未完成"}</h2>
          <p>{busy ? "正在根据你的方向、简历和面试官风格整理本轮问题，请稍候。" : "面试资料已保存，可以调整面试官风格后重试。"}</p>
          {!busy && <><StylePicker catalog={styleCatalog} value={styleSelection} onChange={setStyleSelection} /><button onClick={() => void run(() => preparePlan(styleSelection))}>重试准备</button></>}
        </section>
      )}

      {step === 1 && session.status === "ready_for_interview" && (
        <section className="card">
          <div className="interview-head"><div><h2>面试已准备好</h2><p className="muted">已根据你的研究方向、简历和面试官风格准备本轮约 35 分钟的混合面试，包含口头问题与编程/代码理解实操题。具体问题会在面试中逐个出现。</p></div><StyleBadge style={session.interviewer_style} /></div>
          <button onClick={start} disabled={busy}>{busy ? "准备中…" : "开始面试"}</button>
        </section>
      )}

      {step === 1 && session.status === "interview_in_progress" && (
        <section className="card interview">
          <div className="interview-head"><div><p className="eyebrow">{task && task.type !== "oral" ? `实操 · ${topic || task.title}` : (topic || "动态追问")}</p><h2>面试进行中</h2></div><div className="actions"><StyleBadge style={session.interviewer_style} /><button className="ghost" onClick={() => setPaused((old) => !old)}>{paused ? "继续面试" : "暂停"}</button><button className="ghost" onClick={finish} disabled={busy}>结束面试</button></div></div>
          <p className="muted">当前面试官：{session.interviewer_style?.name || "默认类型"}。可以直接录制口语回答；转写后先由你检查，提交前不会进入面试记录。</p>
          <div className="question">{task && task.type !== "oral" ? task.core_question : question}</div>
          {task && task.type !== "oral" && task.constraints?.length ? <div className="task-constraints"><strong>约束与输入格式</strong><ul>{task.constraints.map((constraint) => <li key={constraint}>{constraint}</li>)}</ul></div> : null}
          {task && task.type !== "oral" && task.materials && <div className="task-material"><strong>任务材料</strong>{Object.entries(task.materials).map(([key, value]) => <div key={key} className="material-item"><b>{key === "schema" ? "数据库结构" : key === "seed" ? "初始数据" : key === "logs" ? "日志" : key === "metrics" ? "指标" : key === "dataset" ? "数据" : key === "prompt" ? "说明" : key}</b>{typeof value === "string" ? <pre>{value}</pre> : <pre>{JSON.stringify(value, null, 2)}</pre>}</div>)}</div>}
          {task && task.type !== "oral" && task.public_samples?.length ? <div className="samples"><strong>公开样例</strong>{task.public_samples.map((sample, index) => <pre key={index}>{sample.rows ? `预期行：${JSON.stringify(sample.rows)}` : `输入：${sample.input}\n输出：${sample.output}`}{sample.explanation ? `\n说明：${sample.explanation}` : ""}</pre>)}</div> : null}
          <div className="history">{turns.slice(-6).map((turn, index) => <div className={turn.role} key={`${turn.role}-${index}`}><b>{turn.role === "candidate" ? "你" : "面试官"}</b><div className="history-content"><span>{turn.content}</span>{turn.submission?.source && <pre className="history-code">{turn.submission.source}</pre>}{turn.submission?.result && <small>测试摘要：{turn.submission.result.status || "未执行"} · 通过 {turn.submission.result.passed ?? 0}/{turn.submission.result.total ?? 0}</small>}</div></div>)}</div>
          {paused ? <div className="notice">面试已暂停，当前问题和已记录回答会保留。</div> : task && task.type !== "oral" ? <div className="practical-editor">
            <div className="task-toolbar"><span className="timer">剩余 {formatSeconds(taskSeconds)}</span><span className="muted">公开试跑最多 {10} 次；最终提交后本题锁定</span>{task.type !== "practical" && task.language_options?.length ? <label>语言<select value={taskLanguage} onChange={(event) => setTaskLanguage(event.target.value)} disabled={busy || task.locked}>{task.language_options.map((language) => <option key={language} value={language}>{language === "python" ? "Python 3.12" : language === "cpp" ? "C++20" : language}</option>)}</select></label> : null}</div>
            {task.type === "code_review" && <p className="muted">先解释问题和最小反例；如果愿意，可在下方提交修正版。</p>}
            {isAnalysisTask ? <div className="analysis-form"><label>结构化判断<textarea value={analysisJudgment} onChange={(event) => setAnalysisJudgment(event.target.value)} placeholder="例如：指标下降主要来自数据分布变化…" rows={3} maxLength={12000} disabled={busy || task.locked} /></label><label>依据<textarea value={analysisEvidence} onChange={(event) => setAnalysisEvidence(event.target.value)} placeholder="引用表格、指标或日志中的具体证据…" rows={4} maxLength={12000} disabled={busy || task.locked} /></label><label>下一步验证方案<textarea value={analysisNextValidation} onChange={(event) => setAnalysisNextValidation(event.target.value)} placeholder="说明一个最小、可执行的验证或排查步骤…" rows={3} maxLength={12000} disabled={busy || task.locked} /></label><textarea value={taskExplanation} onChange={(event) => setTaskExplanation(event.target.value)} placeholder="补充说明（可选）" rows={3} maxLength={12000} disabled={busy || task.locked} /></div> : <textarea className="code-editor" value={taskSource} onChange={(event) => setTaskSource(event.target.value)} placeholder={task.type === "code_review" ? "在这里提交可选修正版…" : task.practical_type === "sql" ? "在这里编写只读 SELECT / CTE…" : "在这里编写代码…"} rows={14} maxLength={65536} disabled={busy || task.locked} spellCheck={false} />}
            {task.type === "code_review" && <textarea value={taskExplanation} onChange={(event) => setTaskExplanation(event.target.value)} placeholder="补充你的解释和最小反例（可选）" rows={4} maxLength={12000} disabled={busy || task.locked} />}
            {taskResult && <div className={`task-result ${taskResult.status === "ok" ? "success" : "failure"}`}><strong>{isAnalysisTask ? "分析已记录" : taskResult.status === "ok" ? "公开测试通过" : "需要检查"}</strong>{!isAnalysisTask && <span>{taskResult.passed ?? 0}/{taskResult.total ?? 0} 个测试</span>}{taskResult.compile_error && <small>编译错误：{taskResult.compile_error}</small>}{taskResult.runtime_error && <small>运行结果：{taskResult.runtime_error}</small>}{taskResult.output_truncated && <small>输出超过限制，已截断。</small>}</div>}
            <div className="answer-actions"><button type="button" className="ghost" onClick={runPublicTask} disabled={busy || task.locked || !practicalCanRun}>{busy ? "执行中…" : isAnalysisTask ? "保存分析草稿" : "试跑公开样例"}</button><button type="button" onClick={submitPracticalTask} disabled={busy || task.locked || !practicalReady}>{busy ? "提交中…" : "最终提交并进入下一题"}</button></div>
          </div> : <form onSubmit={submitAnswer} className="answer"><VoiceRecorder disabled={busy} onTranscribed={(text) => setAnswer((old) => old.trim() ? `${old.trim()}\n${text}` : text)} /><textarea value={answer} onChange={(event) => setAnswer(event.target.value)} placeholder="录音转写会出现在这里，也可以直接输入。输入“跳过”可跳到下一题。" rows={5} maxLength={12000} required /><div className="answer-actions"><button type="button" className="ghost" onClick={() => setAnswer("跳过")}>跳过本题</button><button disabled={busy || !answer.trim()}>{busy ? "处理中…" : "确认并提交回答"}</button></div></form>}
        </section>
      )}

      {step === 2 && !feedback && <section className="card"><h2>面试已结束</h2><p>将根据你的真实回答生成证据化反馈和本轮模拟面试通过概率。该概率不代表最终招生录取结果。</p><button onClick={makeFeedback} disabled={busy}>{busy ? "生成反馈中…" : "生成本轮反馈"}</button></section>}

      {step === 2 && feedback && (
        <section className="card feedback">
          <div className="interview-head"><div><p className="eyebrow">EVIDENCE-BASED REVIEW</p><h2>本轮反馈</h2></div><div className="actions"><StyleBadge style={session.interviewer_style} /><button className="ghost" onClick={() => window.print()}>打印 / 保存</button></div></div>
          <div className="feedback-probability"><span className="eyebrow">本轮模拟面试通过概率</span><strong>{feedback.interview_pass_probability}%</strong><p>仅依据本轮面试表现估计，不等同于最终招生录取率。</p></div>
          <h3>本轮总结</h3><p>{feedback.overall}</p>
          <p className="muted">本轮面试官：{session.interviewer_style?.name || "默认类型"}。证据覆盖：{feedback.evidence_coverage}（信心：{feedback.confidence}）</p>
          <h3>优势</h3><ul>{feedback.strengths.map((item) => <li key={item}>{item}</li>)}</ul>
          <h3>专业知识方面不足</h3>{feedback.professional_knowledge_gaps.length ? feedback.professional_knowledge_gaps.map((item) => <article className="issue" key={item.statement}><strong>{item.category}</strong><p>{item.statement}</p><small>证据：{item.evidence.join("；")}</small><p className="muted">行动：{item.action}</p></article>) : <p className="muted">本轮没有观察到需要优先纠正的专业知识问题。</p>}
          <h3>面试技巧方面不足</h3>{feedback.interview_skill_gaps.length ? feedback.interview_skill_gaps.map((item) => <article className="issue" key={item.statement}><strong>{item.category}</strong><p>{item.statement}</p><small>证据：{item.evidence.join("；")}</small><p className="muted">行动：{item.action}</p></article>) : <p className="muted">本轮没有观察到需要优先纠正的面试技巧问题。</p>}
          <h3>回答改进示例</h3>{feedback.improvement_examples.length ? <ul>{feedback.improvement_examples.map((item) => <li key={item}>{item}</li>)}</ul> : <p className="muted">本轮没有生成单独的回答示例。</p>}
          <h3>三个优先训练动作</h3><ol>{feedback.priority_drills.map((item) => <li key={item}>{item}</li>)}</ol>
          <h3>下一轮建议</h3><p>{feedback.next_round}</p>
          {showNextStyle ? <div className="next-style"><h3>选择下一轮面试官</h3><p className="muted">默认沿用本轮，你可以在准备下一轮前调整。</p><StylePicker catalog={styleCatalog} value={styleSelection} onChange={setStyleSelection} disabled={busy} /><div className="actions"><button className="ghost" onClick={() => setShowNextStyle(false)} disabled={busy}>取消</button><button onClick={() => confirmNextRound(styleSelection)} disabled={busy}>{busy ? "正在准备…" : "确认并准备下一轮"}</button></div></div> : <button onClick={() => { setStyleSelection(selectionFromStyle(session.interviewer_style)); setShowNextStyle(true); }}>开始下一轮</button>}
        </section>
      )}

      <footer>录音仅用于即时转写、不落盘 · 不写入 Git · 真实资料请使用 HTTPS</footer>
    </main>
  );
}

export default App;
