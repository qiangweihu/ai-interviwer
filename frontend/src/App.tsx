import { FormEvent, useEffect, useMemo, useState } from "react";

type Status = "needs_onboarding" | "ready_for_planning" | "ready_for_interview" | "interview_in_progress" | "ready_for_feedback" | "complete";
type Session = { status: Status; profile_revision: number; plan_profile_revision?: number; current_run_id?: string; expires_at: string; profile_complete: boolean; plan_preview?: { duration_minutes: number; main_question_count: number; research_status?: string; topics: { title: string; objective: string; minutes: number }[] } };
type Turn = { role: "interviewer" | "candidate"; content: string };
type Feedback = { overall: string; evidence_coverage: string; confidence: string; ratings: Record<string, { score: number; evidence: string[]; confidence: string }>; strengths: string[]; issues: { category: string; statement: string; evidence: string[]; action: string }[]; improvement_examples: string[]; priority_drills: string[]; next_round: string };

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "include", ...init });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "请求失败，请稍后重试");
  return body as T;
}

function App() {
  const [session, setSession] = useState<Session | null>(null);
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

  const refresh = async () => {
    try {
      const current = await api<Session>("/api/session");
      setSession(current);
      if (current.status === "interview_in_progress") {
        const state = await api<{ question?: string; topic?: string; turns: Turn[] }>("/api/interview");
        setQuestion(state.question || ""); setTopic(state.topic || ""); setTurns(state.turns || []);
      }
      if (current.status === "complete" && current.current_run_id) {
        const result = await api<{ feedback: Feedback }>("/api/feedback");
        setFeedback(result.feedback);
      }
    } catch {
      const created = await api<Session>("/api/session", { method: "POST" });
      setSession(created);
    }
  };

  useEffect(() => { void refresh(); }, []);

  const fail = (reason: unknown) => setError(reason instanceof Error ? reason.message : "请求失败，请稍后重试");
  const run = async (action: () => Promise<void>) => { setBusy(true); setError(""); try { await action(); } catch (reason) { fail(reason); } finally { setBusy(false); } };

  const submitProfile = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      if (!resume) throw new Error("请选择简历文件");
      const form = new FormData(); form.append("direction", direction); form.append("target_group", group); form.append("target_program", program); form.append("resume", resume);
      const next = await api<Session>("/api/profile", { method: "POST", body: form }); setSession(next);
    });
  };

  const makePlan = () => void run(async () => { const next = await api<Session>("/api/plan", { method: "POST" }); setSession(next); });
  const start = () => void run(async () => { const result = await api<{ question: string; topic?: string }>("/api/interview/start", { method: "POST" }); setQuestion(result.question); setTopic(result.topic || ""); setPaused(false); setSession((old) => old ? { ...old, status: "interview_in_progress" } : old); });
  const submitAnswer = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => { const text = answer.trim(); if (!text) return; const requestId = crypto.randomUUID(); setTurns((old) => [...old, { role: "candidate", content: text }]); const result = await api<{ question?: string; topic?: string; done: boolean }>("/api/interview/answer", { method: "POST", headers: { "Content-Type": "application/json", "X-Request-ID": requestId }, body: JSON.stringify({ answer: text, request_id: requestId }) }); setAnswer(""); if (result.done) { setQuestion(""); setSession((old) => old ? { ...old, status: "ready_for_feedback" } : old); } else { setTurns((old) => [...old, { role: "interviewer", content: result.question || "" }]); setQuestion(result.question || ""); setTopic(result.topic || ""); } });
  };
  const finish = () => void run(async () => { await api("/api/interview/end", { method: "POST" }); setQuestion(""); setSession((old) => old ? { ...old, status: "ready_for_feedback" } : old); });
  const makeFeedback = () => void run(async () => { const result = await api<{ feedback: Feedback }>("/api/feedback", { method: "POST" }); setFeedback(result.feedback); setSession((old) => old ? { ...old, status: "complete" } : old); });
  const nextRound = () => void run(async () => { const next = await api<Session>("/api/session/new", { method: "POST" }); setSession(next); setFeedback(null); setTurns([]); setQuestion(""); });

  const step = useMemo(() => {
    if (!session) return 0;
    if (session.status === "needs_onboarding") return 0;
    if (session.status === "ready_for_planning") return 1;
    if (session.status === "ready_for_interview") return 2;
    if (session.status === "interview_in_progress") return 3;
    return 4;
  }, [session]);

  if (!session) return <main className="shell"><p>正在建立匿名会话…</p></main>;
  return <main className="shell">
    <header><div><p className="eyebrow">AI RESEARCH INTERVIEW COACH</p><h1>科研模拟面试官</h1><p className="lead">把简历事实转成一轮可练习、可复盘的课题组面试。</p></div><span className="privacy">匿名 · 24 小时自动清理</span></header>
    <nav className="steps">{["资料", "规划", "开始", "面试", "反馈"].map((label, index) => <span className={index <= step ? "active" : ""} key={label}><b>{index + 1}</b>{label}</span>)}</nav>
    {error && <div className="error" role="alert">{error}</div>}
    {step === 0 && <section className="card"><h2>先建立你的面试档案</h2><p className="muted">只上传脱敏或虚构简历。服务器解析后会立即删除原文件。</p><form onSubmit={submitProfile} className="form"><label>目标科研方向<input value={direction} onChange={(event) => setDirection(event.target.value)} placeholder="例如：视觉表征学习与跨模态检索" required /></label><label>目标课题组 / 导师<input value={group} onChange={(event) => setGroup(event.target.value)} placeholder="可选，未知时留空" /></label><label>项目或招生方向<input value={program} onChange={(event) => setProgram(event.target.value)} placeholder="可选" /></label><label className="upload">简历文件<input type="file" accept=".pdf,.docx,.md,.markdown,.txt" onChange={(event) => setResume(event.target.files?.[0] || null)} required /><small>{resume ? resume.name : "PDF / DOCX / Markdown / TXT，最大 10 MB"}</small></label><button disabled={busy}>{busy ? "解析中…" : "保存资料并继续"}</button></form></section>}
    {step === 1 && <section className="card"><h2>定向面试规划</h2><p>资料已保存。规划器会围绕你的方向检索（若插件可用）并组织约 25 分钟、8–12 个主问题。</p><div className="notice">当前服务器默认使用未联网降级模式；研究资料会明确标注“未核验”。</div><button onClick={makePlan} disabled={busy}>{busy ? "生成中…" : "生成我的面试计划"}</button></section>}
    {step === 2 && session.plan_preview && <section className="card"><h2>计划摘要</h2><p className="muted">约 {session.plan_preview.duration_minutes} 分钟 · {session.plan_preview.main_question_count} 个主问题 · 研究状态：{session.plan_preview.research_status === "verified" ? "已核验" : "降级未核验"}</p><div className="topic-grid">{session.plan_preview.topics.map((item) => <article key={item.title}><strong>{item.title}</strong><span>{item.objective}</span><small>{item.minutes} 分钟</small></article>)}</div><button onClick={start} disabled={busy}>{busy ? "准备中…" : "开始面试"}</button></section>}
    {step === 3 && <section className="card interview"><div className="interview-head"><div><p className="eyebrow">{topic || "动态追问"}</p><h2>面试进行中</h2></div><div className="actions"><button className="ghost" onClick={() => setPaused((old) => !old)}>{paused ? "继续面试" : "暂停"}</button><button className="ghost" onClick={finish} disabled={busy}>结束面试</button></div></div><p className="muted">建议使用系统或输入法的语音转文字。这里不会显示评分；你也可以随时结束。</p><div className="question">{question}</div><div className="history">{turns.slice(-6).map((turn, index) => <div className={turn.role} key={`${turn.role}-${index}`}><b>{turn.role === "candidate" ? "你" : "面试官"}</b><span>{turn.content}</span></div>)}</div>{paused ? <div className="notice">面试已暂停，当前问题和已记录回答会保留。</div> : <form onSubmit={submitAnswer} className="answer"><textarea value={answer} onChange={(event) => setAnswer(event.target.value)} placeholder="用自然口语回答…输入“跳过”可跳到下一题，输入“结束面试”可提前结束" rows={5} maxLength={12000} required /><div className="answer-actions"><button type="button" className="ghost" onClick={() => setAnswer("跳过")}>跳过本题</button><button disabled={busy || !answer.trim()}>{busy ? "处理中…" : "提交回答"}</button></div></form>}</section>}
    {step === 4 && !feedback && <section className="card"><h2>面试已结束</h2><p>将根据你的真实回答生成证据化反馈，不会做录取判断。</p><button onClick={makeFeedback} disabled={busy}>{busy ? "生成反馈中…" : "生成本轮反馈"}</button></section>}
    {step === 4 && feedback && <section className="card feedback"><div className="interview-head"><div><p className="eyebrow">EVIDENCE-BASED REVIEW</p><h2>本轮反馈</h2></div><button className="ghost" onClick={() => window.print()}>打印 / 保存</button></div><p>{feedback.overall}</p><p className="muted">证据覆盖：{feedback.evidence_coverage}（信心：{feedback.confidence}）</p><h3>五项评价</h3><div className="ratings">{Object.entries(feedback.ratings).map(([name, rating]) => <article key={name}><strong>{name}</strong><span className="score">{rating.score} / 5</span><small>{rating.evidence.join("；")}</small></article>)}</div><h3>优势</h3><ul>{feedback.strengths.map((item) => <li key={item}>{item}</li>)}</ul><h3>主要问题</h3>{feedback.issues.map((item) => <article className="issue" key={item.statement}><strong>{item.category}</strong><p>{item.statement}</p><small>证据：{item.evidence.join("；")}</small><p className="muted">行动：{item.action}</p></article>)}<h3>三个优先训练动作</h3><ol>{feedback.priority_drills.map((item) => <li key={item}>{item}</li>)}</ol><h3>下一轮建议</h3><p>{feedback.next_round}</p><button onClick={nextRound}>开始下一轮</button></section>}
    <footer>不保存音频 · 不写入 Git · 如需真实简历，请先等待 HTTPS 版本</footer>
  </main>;
}

export default App;
