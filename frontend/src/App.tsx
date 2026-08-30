import { FormEvent, useEffect, useMemo, useState } from "react";

type Status = "needs_onboarding" | "ready_for_planning" | "ready_for_interview" | "interview_in_progress" | "ready_for_feedback" | "complete";
type StyleSelection = { control: "dominant" | "listener"; tone: "strict" | "friendly"; plan_adherence: "structured" | "flexible" };
type PublicStyle = StyleSelection & { version: string; preset_id: string; name: string; summary: string; traits: string[] };
type StyleOption = { value: string; label: string; description: string };
type StyleCatalog = { version: string; default_preset_id: string; dimensions: Record<string, { label: string; options: StyleOption[] }>; presets: PublicStyle[] };
type Session = { status: Status; profile_revision: number; plan_profile_revision?: number; current_run_id?: string; expires_at: string; profile_complete: boolean; plan_preview?: { duration_minutes: number; main_question_count: number; research_status?: string; topics: { title: string; objective: string; minutes: number }[] }; interviewer_style?: PublicStyle };
type Turn = { role: "interviewer" | "candidate"; content: string };
type Feedback = { overall: string; evidence_coverage: string; confidence: string; ratings: Record<string, { score: number; evidence: string[]; confidence: string }>; strengths: string[]; issues: { category: string; statement: string; evidence: string[]; action: string }[]; improvement_examples: string[]; priority_drills: string[]; next_round: string };

const DEFAULT_STYLE: StyleSelection = { control: "dominant", tone: "friendly", plan_adherence: "structured" };
const STYLE_AXES: { key: keyof StyleSelection; label: string }[] = [
  { key: "control", label: "对话控制" },
  { key: "tone", label: "沟通氛围" },
  { key: "plan_adherence", label: "流程自由度" },
];

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
  if (webCrypto && typeof webCrypto.randomUUID === "function") {
    return webCrypto.randomUUID();
  }
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

function selectionFromStyle(style?: PublicStyle): StyleSelection {
  return style ? { control: style.control, tone: style.tone, plan_adherence: style.plan_adherence } : DEFAULT_STYLE;
}

function StylePicker({ catalog, value, onChange, disabled = false }: { catalog: StyleCatalog; value: StyleSelection; onChange: (next: StyleSelection) => void; disabled?: boolean }) {
  const selected = catalog.presets.find((preset) => preset.control === value.control && preset.tone === value.tone && preset.plan_adherence === value.plan_adherence) || catalog.presets.find((preset) => preset.preset_id === catalog.default_preset_id);
  return <div className="style-picker">
    <div className="style-axes">
      {STYLE_AXES.map(({ key, label }) => <fieldset key={key} disabled={disabled}>
        <legend>{label}</legend>
        <div className="style-options">
          {catalog.dimensions[key]?.options.map((option) => <label className="style-option" key={option.value}>
            <input type="radio" name={`style-${key}`} checked={value[key] === option.value} onChange={() => onChange({ ...value, [key]: option.value } as StyleSelection)} />
            <span><strong>{option.label}</strong><small>{option.description}</small></span>
          </label>)}
        </div>
      </fieldset>)}
    </div>
    {selected && <div className="style-preview"><div><span className="eyebrow">当前面试官</span><h3>{selected.name}</h3><p>{selected.summary}</p></div><ul>{selected.traits.map((trait) => <li key={trait}>{trait}</li>)}</ul></div>}
  </div>;
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
  const [answer, setAnswer] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [paused, setPaused] = useState(false);

  // Planning is an internal preparation step. Keep the endpoint available for
  // retries, but never make the user navigate through a separate planning page.
  const preparePlan = async (selection = styleSelection) => {
    const next = await api<Session>("/api/plan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ interviewer_style: selection }) });
    setSession(next);
    if (next.interviewer_style) setStyleSelection(selectionFromStyle(next.interviewer_style));
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
        const state = await api<{ question?: string; topic?: string; turns: Turn[] }>("/api/interview");
        setQuestion(state.question || ""); setTopic(state.topic || ""); setTurns(state.turns || []);
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
        await refresh();
      } catch (reason) { fail(reason); }
    })();
  }, []);

  const fail = (reason: unknown) => setError(reason instanceof Error ? reason.message : "请求失败，请稍后重试");
  const run = async (action: () => Promise<void>) => { setBusy(true); setError(""); try { await action(); } catch (reason) { fail(reason); } finally { setBusy(false); } };

  const submitProfile = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      if (!resume) throw new Error("请选择简历文件");
      const form = new FormData(); form.append("direction", direction); form.append("target_group", group); form.append("target_program", program); form.append("resume", resume);
      const next = await api<Session>("/api/profile", { method: "POST", body: form });
      setSession(next);
      await preparePlan(styleSelection);
    });
  };

  const start = () => void run(async () => { const result = await api<{ question: string; topic?: string }>("/api/interview/start", { method: "POST" }); setQuestion(result.question); setTopic(result.topic || ""); setPaused(false); setSession((old) => old ? { ...old, status: "interview_in_progress" } : old); });
  const submitAnswer = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => { const text = answer.trim(); if (!text) return; const requestId = createRequestId(); setTurns((old) => [...old, { role: "candidate", content: text }]); const result = await api<{ question?: string; topic?: string; done: boolean }>("/api/interview/answer", { method: "POST", headers: { "Content-Type": "application/json", "X-Request-ID": requestId }, body: JSON.stringify({ answer: text, request_id: requestId }) }); setAnswer(""); if (result.done) { setQuestion(""); setSession((old) => old ? { ...old, status: "ready_for_feedback" } : old); } else { setTurns((old) => [...old, { role: "interviewer", content: result.question || "" }]); setQuestion(result.question || ""); setTopic(result.topic || ""); } });
  };
  const finish = () => void run(async () => { await api("/api/interview/end", { method: "POST" }); setQuestion(""); setSession((old) => old ? { ...old, status: "ready_for_feedback" } : old); });
  const makeFeedback = () => void run(async () => { const result = await api<{ feedback: Feedback }>("/api/feedback", { method: "POST" }); setFeedback(result.feedback); setSession((old) => old ? { ...old, status: "complete" } : old); });
  const confirmNextRound = () => void run(async () => { const next = await api<Session>("/api/session/new", { method: "POST" }); setSession(next); setFeedback(null); setTurns([]); setQuestion(""); setShowNextStyle(false); await preparePlan(styleSelection); });

  const step = useMemo(() => {
    if (!session) return 0;
    if (session.status === "needs_onboarding") return 0;
    if (session.status === "ready_for_planning") return 0;
    if (session.status === "ready_for_interview" || session.status === "interview_in_progress") return 1;
    return 2;
  }, [session]);

  if (!session || !styleCatalog) return <main className="shell"><p>正在建立匿名会话…</p></main>;
  return <main className="shell">
    <header><div><p className="eyebrow">AI RESEARCH INTERVIEW COACH</p><h1>科研模拟面试官</h1><p className="lead">把简历事实转成一轮可练习、可复盘的课题组面试。</p></div><span className="privacy">匿名 · 24 小时自动清理</span></header>
    <nav className="steps">{["资料", "面试", "反馈"].map((label, index) => <span className={index <= step ? "active" : ""} key={label}><b>{index + 1}</b>{label}</span>)}</nav>
    {error && <div className="error" role="alert">{error}</div>}
    {session.status === "needs_onboarding" && <section className="card"><h2>先建立你的面试档案</h2><p className="muted">只上传脱敏或虚构简历。服务器解析后会立即删除原文件。</p><form onSubmit={submitProfile} className="form"><label>目标科研方向<input value={direction} onChange={(event) => setDirection(event.target.value)} placeholder="例如：视觉表征学习与跨模态检索" required /></label><label>目标课题组 / 导师<input value={group} onChange={(event) => setGroup(event.target.value)} placeholder="可选，未知时留空" /></label><label>项目或招生方向<input value={program} onChange={(event) => setProgram(event.target.value)} placeholder="可选" /></label><label className="upload">简历文件<input type="file" accept=".pdf,.docx,.md,.markdown,.txt" onChange={(event) => setResume(event.target.files?.[0] || null)} required /><small>{resume ? resume.name : "PDF / DOCX / Markdown / TXT，最大 10 MB"}</small></label><div className="style-section"><h3>选择面试官风格</h3><p className="muted">风格只改变提问方式，不改变评价标准。</p><StylePicker catalog={styleCatalog} value={styleSelection} onChange={setStyleSelection} disabled={busy} /></div><button disabled={busy}>{busy ? "正在准备面试…" : "保存资料并准备面试"}</button></form></section>}
    {session.status === "ready_for_planning" && <section className="card"><h2>{busy ? "正在准备面试" : "面试准备未完成"}</h2><p>{busy ? "正在根据你的方向和简历整理本轮问题，请稍候。" : "面试资料已保存，可以调整面试官风格后重试。"}</p>{!busy && <><StylePicker catalog={styleCatalog} value={styleSelection} onChange={setStyleSelection} /><button onClick={() => void run(() => preparePlan(styleSelection))}>重试准备</button></>}</section>}
    {step === 1 && session.status === "ready_for_interview" && <section className="card"><div className="interview-head"><div><h2>面试已准备好</h2><p className="muted">已根据你的研究方向和简历准备本轮约 25 分钟的自适应面试。具体问题会在面试中逐个出现。</p></div><StyleBadge style={session.interviewer_style} /></div><button onClick={start} disabled={busy}>{busy ? "准备中…" : "开始面试"}</button></section>}
    {step === 1 && session.status === "interview_in_progress" && <section className="card interview"><div className="interview-head"><div><p className="eyebrow">{topic || "动态追问"}</p><h2>面试进行中</h2></div><div className="actions"><StyleBadge style={session.interviewer_style} /><button className="ghost" onClick={() => setPaused((old) => !old)}>{paused ? "继续面试" : "暂停"}</button><button className="ghost" onClick={finish} disabled={busy}>结束面试</button></div></div><p className="muted">当前面试官：{session.interviewer_style?.name || "默认类型"}。这里不会显示评分；你也可以随时结束。</p><div className="question">{question}</div><div className="history">{turns.slice(-6).map((turn, index) => <div className={turn.role} key={`${turn.role}-${index}`}><b>{turn.role === "candidate" ? "你" : "面试官"}</b><span>{turn.content}</span></div>)}</div>{paused ? <div className="notice">面试已暂停，当前问题和已记录回答会保留。</div> : <form onSubmit={submitAnswer} className="answer"><textarea value={answer} onChange={(event) => setAnswer(event.target.value)} placeholder="用自然口语回答…输入“跳过”可跳到下一题，输入“结束面试”可提前结束" rows={5} maxLength={12000} required /><div className="answer-actions"><button type="button" className="ghost" onClick={() => setAnswer("跳过")}>跳过本题</button><button disabled={busy || !answer.trim()}>{busy ? "处理中…" : "提交回答"}</button></div></form>}</section>}
    {step === 2 && !feedback && <section className="card"><h2>面试已结束</h2><p>将根据你的真实回答生成证据化反馈，不会做录取判断。</p><button onClick={makeFeedback} disabled={busy}>{busy ? "生成反馈中…" : "生成本轮反馈"}</button></section>}
    {step === 2 && feedback && <section className="card feedback"><div className="interview-head"><div><p className="eyebrow">EVIDENCE-BASED REVIEW</p><h2>本轮反馈</h2></div><div className="actions"><StyleBadge style={session.interviewer_style} /><button className="ghost" onClick={() => window.print()}>打印 / 保存</button></div></div><p>{feedback.overall}</p><p className="muted">本轮面试官：{session.interviewer_style?.name || "默认类型"}。证据覆盖：{feedback.evidence_coverage}（信心：{feedback.confidence}）</p><h3>五项评价</h3><div className="ratings">{Object.entries(feedback.ratings).map(([name, rating]) => <article key={name}><strong>{name}</strong><span className="score">{rating.score} / 5</span><small>{rating.evidence.join("；")}</small></article>)}</div><h3>优势</h3><ul>{feedback.strengths.map((item) => <li key={item}>{item}</li>)}</ul><h3>主要问题</h3>{feedback.issues.map((item) => <article className="issue" key={item.statement}><strong>{item.category}</strong><p>{item.statement}</p><small>证据：{item.evidence.join("；")}</small><p className="muted">行动：{item.action}</p></article>)}<h3>三个优先训练动作</h3><ol>{feedback.priority_drills.map((item) => <li key={item}>{item}</li>)}</ol><h3>下一轮建议</h3><p>{feedback.next_round}</p>{showNextStyle ? <div className="next-style"><h3>选择下一轮面试官</h3><p className="muted">默认沿用本轮，你可以在准备下一轮前调整。</p><StylePicker catalog={styleCatalog} value={styleSelection} onChange={setStyleSelection} disabled={busy} /><div className="actions"><button className="ghost" onClick={() => setShowNextStyle(false)} disabled={busy}>取消</button><button onClick={confirmNextRound} disabled={busy}>{busy ? "正在准备…" : "确认并准备下一轮"}</button></div></div> : <button onClick={() => { setStyleSelection(selectionFromStyle(session.interviewer_style)); setShowNextStyle(true); }}>开始下一轮</button>}</section>}
    <footer>不保存音频 · 不写入 Git · 如需真实简历，请先等待 HTTPS 版本</footer>
  </main>;
}

export default App;
