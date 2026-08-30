import { ChangeEvent, useEffect, useRef, useState } from "react";

type SpeechConfig = {
  enabled: boolean;
  max_audio_bytes: number;
  max_audio_seconds: number;
  accepted_types: string[];
};

type Props = {
  disabled?: boolean;
  onTranscribed: (text: string) => void;
};

const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/mp4",
  "audio/webm",
  "audio/ogg;codecs=opus",
];

function recordingMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type));
}

function extensionFor(type: string): string {
  if (type.includes("mp4")) return "m4a";
  if (type.includes("ogg")) return "ogg";
  if (type.includes("wav")) return "wav";
  return "webm";
}

function mimeForFile(file: File): string {
  if (file.type && file.type !== "application/octet-stream") return file.type;
  const extension = file.name.split(".").pop()?.toLowerCase();
  return ({ m4a: "audio/mp4", mp4: "audio/mp4", mp3: "audio/mpeg", wav: "audio/wav", ogg: "audio/ogg", flac: "audio/flac", aac: "audio/aac" } as Record<string, string>)[extension || ""] || "audio/webm";
}

export default function VoiceRecorder({ disabled = false, onTranscribed }: Props) {
  const [config, setConfig] = useState<SpeechConfig | null>(null);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [message, setMessage] = useState("");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const intervalRef = useRef<number | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const releaseMedia = () => {
    if (intervalRef.current !== null) window.clearInterval(intervalRef.current);
    intervalRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    recorderRef.current = null;
  };

  useEffect(() => {
    void fetch("/api/speech/config", { credentials: "include" })
      .then(async (response) => {
        if (!response.ok) throw new Error("无法读取语音服务状态");
        setConfig(await response.json() as SpeechConfig);
      })
      .catch((reason) => setMessage(reason instanceof Error ? reason.message : "无法读取语音服务状态"));
    return releaseMedia;
  }, []);

  const transcribe = async (file: File) => {
    if (!config) return;
    if (file.size > config.max_audio_bytes) {
      setMessage(`录音不能超过 ${Math.floor(config.max_audio_bytes / 1024 / 1024)} MB。`);
      return;
    }
    setTranscribing(true);
    setMessage("正在本机识别口语，首次使用可能需要准备模型，请稍候…");
    try {
      const response = await fetch("/api/interview/transcribe", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": mimeForFile(file) },
        body: file,
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "语音识别失败，请重试");
      const text = String(body.text || "").trim();
      if (!text) throw new Error("没有识别到清晰语音，请重试");
      onTranscribed(text);
      setMessage("识别完成。请检查下方文字，确认无误后再提交回答。");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "语音识别失败，请重试");
    } finally {
      setTranscribing(false);
    }
  };

  const startRecording = async () => {
    setMessage("");
    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
        throw new Error("当前浏览器不支持网页录音，请改用“选择录音文件”。");
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const preferred = recordingMimeType();
      const recorder = preferred ? new MediaRecorder(stream, { mimeType: preferred }) : new MediaRecorder(stream);
      streamRef.current = stream;
      recorderRef.current = recorder;
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onerror = () => {
        setMessage("录音发生错误，请重新录制。");
        setRecording(false);
        releaseMedia();
      };
      recorder.onstop = () => {
        const type = recorder.mimeType || preferred || "audio/webm";
        const blob = new Blob(chunksRef.current, { type });
        releaseMedia();
        setRecording(false);
        if (!blob.size) {
          setMessage("没有录到声音，请检查麦克风权限后重试。");
          return;
        }
        const file = new File([blob], `answer.${extensionFor(type)}`, { type });
        void transcribe(file);
      };
      recorder.start(1000);
      setElapsed(0);
      setRecording(true);
      intervalRef.current = window.setInterval(() => {
        setElapsed((seconds) => {
          const next = seconds + 1;
          if (config && next >= config.max_audio_seconds && recorder.state === "recording") recorder.stop();
          return next;
        });
      }, 1000);
    } catch (reason) {
      releaseMedia();
      setMessage(reason instanceof Error ? reason.message : "无法使用麦克风，请检查浏览器权限。");
    }
  };

  const stopRecording = () => {
    const recorder = recorderRef.current;
    if (recorder?.state === "recording") recorder.stop();
  };

  const pickFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) void transcribe(file);
  };

  if (!config) return message ? <p className="voice-message" role="status">{message}</p> : null;
  if (!config.enabled) return <p className="voice-message">服务器暂未启用语音识别，你仍可输入文字回答。</p>;

  const insecure = !window.isSecureContext && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1";
  const unavailable = disabled || transcribing;
  return <div className="voice-recorder">
    <div className="voice-actions">
      {!recording ? <button
        type="button"
        className="record-button"
        onClick={() => void startRecording()}
        disabled={unavailable || insecure}
        title={insecure ? "网页麦克风需要 HTTPS" : undefined}
      >{transcribing ? "识别中…" : "● 开始语音回答"}</button> : <button type="button" className="stop-button" onClick={stopRecording}>■ 停止并转写（{elapsed}s）</button>}
      <button type="button" className="ghost" onClick={() => fileRef.current?.click()} disabled={unavailable || recording}>选择录音文件</button>
      <input ref={fileRef} className="sr-only" type="file" accept="audio/*,.m4a,.mp3,.wav,.webm,.ogg,.flac" onChange={pickFile} />
    </div>
    {insecure && <p className="voice-message">当前页面不是 HTTPS，浏览器会禁止直接使用麦克风；可先上传录音文件，或为服务器配置 HTTPS。</p>}
    {message && <p className="voice-message" role="status">{message}</p>}
  </div>;
}
