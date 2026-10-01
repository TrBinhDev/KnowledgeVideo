"use client";

import * as RadixSelect from "@radix-ui/react-select";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type Data = Record<string, any>;
type Kind = "image" | "clip";
type Mode = "auto" | "manual";
type Tab = "create" | "history" | "templates" | "settings";
type Step = "content" | "topic" | "script" | "source" | "scenes" | "look" | "finish";

const stepsFor = (kind: Kind, mode: Mode): { key: Step; title: string }[] => mode === "auto"
  ? [
      { key: "content", title: "Nội dung" },
      ...(kind === "clip" ? [{ key: "source" as Step, title: "Video nguồn" }] : []),
      { key: "look", title: "Diện mạo" },
      { key: "finish", title: "Tạo video" },
    ]
  : [
      { key: "content", title: "Nội dung" },
      { key: "topic", title: "Chủ đề" },
      { key: "script", title: "Kịch bản" },
      { key: "scenes", title: kind === "image" ? "Cảnh & ảnh" : "Cảnh & clip" },
      { key: "look", title: "Diện mạo" },
      { key: "finish", title: "Tạo video" },
    ];

const defaults: Data = {
  kind: "image", content_type: "kien_thuc", category: "lich_su", duration: 60,
  voice: "vi-VN-HoaiMyNeural", style: "ke_chuyen", points: null,
  scene_choice: "auto", provider: "ollama", model: "", vision_ai: "same",
  mode: "keywords", input: "", source: "", topic: "", clip_link: "",
  clip_query: "", clip_filter: "real",
};
const renderDefaults: Data = {
  template: "history-scroll", transition: "template", scene_timing: "sentences",
  subtitle_style: "highlight", resolution: "1080x1920", music_volume: 15, music_source: "",
};

const iconPaths: Record<string, React.ReactNode> = {
  play: <><path d="m9 6 10 6-10 6V6Z"/></>,
  image: <><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m3 17 5-5 4 4 3-3 6 6"/></>,
  film: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4m-4 6h4m10-6h4m-4 6h4"/></>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  layers: <><path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/></>,
  settings: <><circle cx="12" cy="12" r="3"/><path d="m19.4 15 .1.1 1.4 1.1-1.5 2.6-1.7-.6a8 8 0 0 1-2.1 1.2L15.3 21h-3l-.3-1.6a8 8 0 0 1-2.1-1.2l-1.7.6-1.5-2.6 1.4-1.1a8 8 0 0 1 0-2.4l-1.4-1.1L8.2 9l1.7.6A8 8 0 0 1 12 8.4L12.3 7h3l.3 1.4a8 8 0 0 1 2.1 1.2l1.7-.6 1.5 2.6-1.4 1.1a8 8 0 0 1 0 2.3Z" transform="translate(-1.5 -1.5)"/></>,
  spark: <><path d="m12 2 1.9 6.1L20 10l-6.1 1.9L12 18l-1.9-6.1L4 10l6.1-1.9L12 2Zm7 14 .7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16Z"/></>,
  arrow: <><path d="M4 12h16m-6-6 6 6-6 6"/></>,
  back: <><path d="M20 12H4m6-6-6 6 6 6"/></>,
  check: <><path d="m5 12 4 4L19 6"/></>,
  folder: <><path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10H3V7Z"/></>,
  refresh: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M5.8 9A7 7 0 0 1 18 7l2 5M4 12l2 5a7 7 0 0 0 12.2-2"/></>,
  volume: <><path d="M4 9h4l5-4v14l-5-4H4V9Zm12-1a6 6 0 0 1 0 8m2-11a10 10 0 0 1 0 14"/></>,
  upload: <><path d="M12 16V4m-5 5 5-5 5 5M4 17v3h16v-3"/></>,
  link: <><path d="M10 13a5 5 0 0 0 7 .5l2-2a5 5 0 0 0-7-7l-1.1 1.1M14 11a5 5 0 0 0-7-.5l-2 2a5 5 0 0 0 7 7l1.1-1.1"/></>,
};
function Icon({ name, size = 20 }: { name: string; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{iconPaths[name] || iconPaths.spark}</svg>;
}
function LocalMedia({ path, video = false, className = "" }: { path?: string; video?: boolean; className?: string }) {
  const [url, setUrl] = useState("");
  useEffect(() => { let alive = true; setUrl(""); if (path && window.kv) window.kv.mediaUrl(path).then(v => { if (alive) setUrl(v); }); return () => { alive = false; }; }, [path]);
  if (!url) return <div className={`media-empty ${className}`}><Icon name={video ? "play" : "image"} size={30}/></div>;
  return video ? <video className={className} src={url} controls playsInline/> : <img className={className} src={url} alt="Xem trước"/>;
}
function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return <label className="field"><span className="field-label">{label}</span>{children}{hint && <span className="field-hint">{hint}</span>}</label>;
}
// Radix reserves "" for "no value", but several lists use "" as a real choice ("Tự động", "Mặc định").
const EMPTY_CHOICE = "__empty__";
function Select({ value, onChange, options }: { value: string | number; onChange: (v: string) => void; options: [string, string][] }) {
  const current = String(value ?? "");
  return <RadixSelect.Root value={current === "" ? EMPTY_CHOICE : current} onValueChange={v => onChange(v === EMPTY_CHOICE ? "" : v)}>
    <RadixSelect.Trigger className="kv-select-trigger"><RadixSelect.Value/><RadixSelect.Icon className="kv-select-chevron"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg></RadixSelect.Icon></RadixSelect.Trigger>
    <RadixSelect.Portal><RadixSelect.Content className="kv-select-content" position="popper" sideOffset={6}><RadixSelect.Viewport className="kv-select-viewport">
      {options.map(([key, label]) => <RadixSelect.Item key={key} value={key === "" ? EMPTY_CHOICE : key} className="kv-select-item"><RadixSelect.ItemText>{label}</RadixSelect.ItemText><RadixSelect.ItemIndicator className="kv-select-check"><Icon name="check" size={14}/></RadixSelect.ItemIndicator></RadixSelect.Item>)}
    </RadixSelect.Viewport></RadixSelect.Content></RadixSelect.Portal>
  </RadixSelect.Root>;
}
function Pill({ active, children, onClick }: { active?: boolean; children: React.ReactNode; onClick: () => void }) {
  return <button type="button" className={`pill ${active ? "active" : ""}`} onClick={onClick}>{children}</button>;
}
function Card({ title, description, children, className = "" }: { title?: string; description?: string; children: React.ReactNode; className?: string }) {
  return <section className={`panel ${className}`}>{title && <div className="panel-heading"><h2>{title}</h2>{description && <p>{description}</p>}</div>}{children}</section>;
}

type LogKind = "start" | "progress" | "done" | "warn" | "error";
interface LogEntry { id: number; time: Date; kind: LogKind; text: string; percent: number }
const logLabels: Record<LogKind, string> = { start: "Bắt đầu", progress: "Đang làm", done: "Xong", warn: "Cảnh báo", error: "Lỗi" };
const formatBytes = (bytes: number) => bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(1)} GB` : bytes >= 1024 ** 2 ? `${Math.round(bytes / 1024 ** 2)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
const specialFolders: Record<string, string> = { _clip_cache: "Cache clip YouTube", _voice_cache: "Cache giọng đọc", _gallery: "Ảnh mẫu (cũ)", logs: "Nhật ký", "": "Tệp lẻ" };
// Run folders are "YYYYMMDD_HHMMSS__slug": show the slug as words.
const folderLabel = (name: string) => specialFolders[name] ?? (name.replace(/^\d{8}_\d{6}__/, "").replace(/-/g, " ") || name);
const formatSeconds = (seconds: number) => seconds < 60 ? `${seconds.toFixed(seconds < 10 ? 1 : 0)} giây` : `${Math.floor(seconds / 60)} phút ${Math.round(seconds % 60)} giây`;
const clock = (time: Date) => time.toLocaleTimeString("vi-VN", { hour12: false });
/** Electron wraps bridge errors as "Error invoking remote method 'kv:call': Error: <message>"; keep the message. */
function readableError(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  const text = raw.replace(/^Error invoking remote method '[^']+':\s*/, "").replace(/^Error:\s*/, "");
  const crashed = text.match(/Python backend stopped \(([^)]*)\)/);
  if (crashed) return `Phần xử lý Python bị dừng đột ngột (mã ${crashed[1]}). Tác vụ vừa rồi không hoàn tất; bấm lại để chạy tiếp, backend sẽ tự khởi động lại.`;
  return text;
}

const templateNotes: Data = {
  "history-scroll": ["CỔ THƯ", "Nền giấy, dấu son và màu sepia", "scroll"],
  "history-imperial": ["HOÀNG TRIỀU", "Đỏ son và điểm nhấn vàng kim", "imperial"],
  "history-archive": ["TƯ LIỆU", "Đen trắng, khung phim tư liệu", "archive"],
  "history-inkwash": ["THỦY MẶC", "Giấy ngà, mực tàu và dấu son", "inkwash"],
  "history-battle": ["CHIẾN SỬ", "Xanh rêu, lưới bản đồ tác chiến", "battle"],
  "history-modern": ["HIỆN ĐẠI", "Phẳng, màu nổi, chữ không chân", "modern"],
};
const transitionNotes: Data = {
  template: "Theo mẫu", fade: "Mờ dần", dissolve: "Hòa tan", fadeblack: "Chớp đen",
  smoothleft: "Lướt ngang", hblur: "Nhòe ngang", none: "Cắt thẳng",
};
const flowNotes: Record<string, [string, string]> = {
  "image-auto": ["Ảnh · Tự động", "Từ ý tưởng này, ứng dụng sẽ viết lời kể, chia cảnh, tìm ảnh rồi dựng video sau khi bạn chọn diện mạo."],
  "clip-auto": ["Clip · Tự động", "Ứng dụng sẽ viết lời kể và ghép shot từ video nguồn bạn chọn ở bước kế tiếp."],
  "image-manual": ["Ảnh · Thủ công", "Bạn sẽ duyệt chủ đề, sửa kịch bản và chọn ảnh cho từng cảnh trước khi dựng."],
  "clip-manual": ["Clip · Thủ công", "Bạn sẽ duyệt lời kể, chọn video nguồn và chỉnh từng shot trước khi dựng."],
};
const settingFields: [string, string, string][] = [
  ["KV_GEMINI_API_KEY", "Gemini API key", "password"], ["KV_GEMINI_MODEL", "Gemini model", "text"],
  ["KV_GEMINI_IMAGE_MODEL", "Gemini image model", "text"], ["KV_GATEWAY_API_KEY", "Gateway API key", "password"],
  ["KV_GATEWAY_BASE_URL", "Gateway URL", "text"], ["KV_GATEWAY_MODEL", "Gateway model", "text"],
  ["KV_OLLAMA_URL", "Ollama URL", "text"], ["KV_OLLAMA_MODEL", "Ollama model", "text"],
  ["KV_OLLAMA_TIMEOUT_SECONDS", "Ollama timeout (giây)", "number"], ["KV_VISION_MODEL", "Model xem clip", "text"],
  ["KV_OUTPUT_DIR", "Thư mục video", "text"], ["KV_CLIP_CACHE_MB", "Cache clip (MB)", "number"],
  ["KV_HTTP_USER_AGENT", "Wikimedia User-Agent", "text"], ["KV_VIDEO_FONT", "Font trên video", "text"],
];

export default function Home() {
  const [tab, setTab] = useState<Tab>("create");
  const [kind, setKind] = useState<Kind | null>(null);
  const [mode, setMode] = useState<Mode | null>(null);
  const [stepIndex, setStepIndex] = useState(0);
  // Furthest step reached in this project: going back to step 2 keeps steps up to here clickable.
  const [reached, setReached] = useState(0);
  useEffect(() => { setReached(r => Math.max(r, stepIndex)); }, [stepIndex]);
  const [state, setState] = useState<Data>({ ...defaults });
  const [directory, setDirectory] = useState("");
  const [render, setRender] = useState<Data>({ ...renderDefaults });
  const [catalog, setCatalog] = useState<Data>({});
  const [runs, setRuns] = useState<Data[]>([]);
  const [settings, setSettings] = useState<Data>({});
  const [outputDir, setOutputDir] = useState("");
  const [cacheMb, setCacheMb] = useState(0);
  const [busy, setBusy] = useState(false);
  const [storage, setStorage] = useState<{ total: number; folders: { name: string; bytes: number }[] } | null>(null);
  const [status, setStatus] = useState("");
  const [percent, setPercent] = useState(-1);
  const [notice, setNotice] = useState("");
  const [failure, setFailure] = useState<{ title: string; text: string } | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [logOpen, setLogOpen] = useState(false);
  const logCounter = useRef(0);
  const logEnd = useRef<HTMLDivElement>(null);
  const [topics, setTopics] = useState<Data[]>([]);
  const [inputType, setInputType] = useState<"keywords" | "source_ai" | "source_verbatim" | "json">("keywords");
  const [selectedScene, setSelectedScene] = useState(0);
  const [gallery, setGallery] = useState<Data>({});
  const [galleryTransition, setGalleryTransition] = useState("template");
  const [previewPath, setPreviewPath] = useState("");
  const [sourceCandidates, setSourceCandidates] = useState<Data[]>([]);
  const [outlineText, setOutlineText] = useState("");
  const [models, setModels] = useState<string[]>([]);

  const errorCount = logs.filter(entry => entry.kind === "error").length;
  const warnCount = logs.filter(entry => entry.kind === "warn").length;
  useEffect(() => { if (logOpen) logEnd.current?.scrollIntoView({ block: "end" }); }, [logs, logOpen]);
  const steps = useMemo(() => kind && mode ? stepsFor(kind, mode) : [], [kind, mode]);
  const step = steps[stepIndex]?.key;
  const patch = (values: Data) => setState(previous => ({ ...previous, ...values }));
  const patchRender = (values: Data) => setRender(previous => ({ ...previous, ...values }));
  // The Python bridge runs one request at a time and rejects any request sent while another is running
  // ("Một tác vụ khác đang chạy"), e.g. bootstrap and the model list both fired on start. Queue them instead.
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const call = useCallback(<T,>(method: string, params: Data = {}): Promise<T> => {
    if (!window.kv) return Promise.reject(new Error("Hãy mở giao diện bằng Electron: npm run dev hoặc npm start."));
    const run = queue.current.catch(() => undefined).then(() => window.kv!.call<T>(method, params));
    queue.current = run.catch(() => undefined);
    return run;
  }, []);
  const addLog = useCallback((kind: LogKind, text: string, percent = -1) => {
    setLogs(previous => {
      const last = previous[previous.length - 1];
      if (kind === "progress" && last?.kind === "progress" && last.text === text) {
        return [...previous.slice(0, -1), { ...last, percent }];  // same stage, newer percent
      }
      return [...previous, { id: ++logCounter.current, time: new Date(), kind, text, percent }].slice(-400);
    });
  }, []);
  const work = useCallback(async (label: string, action: () => Promise<void>) => {
    setBusy(true); setNotice(""); setStatus(label); setPercent(-1);
    const started = Date.now();
    addLog("start", label);
    try {
      await action(); setStatus("");
      addLog("done", `${label} xong · ${formatSeconds((Date.now() - started) / 1000)}`);
    } catch (error) {
      const text = readableError(error);
      setNotice(text); setFailure({ title: label, text }); setStatus("");
      addLog("error", `${label}: ${text}`);
    } finally { setBusy(false); }
  }, [addLog]);
  const warn = useCallback((warnings: string[] | undefined) => {
    if (!warnings?.length) return;
    setNotice(warnings.join(" · "));
    warnings.forEach(text => addLog("warn", text));
  }, [addLog]);

  useEffect(() => {
    const off = window.kv?.onProgress(value => { setStatus(value.label); setPercent(value.percent); addLog("progress", value.label, value.percent); });
    if (window.kv) call<Data>("bootstrap").then(data => {
      setCatalog(data.catalog || {}); setSettings(data.settings || {}); setRuns(data.runs || []);
      setOutputDir(data.output_dir || ""); setCacheMb(data.cache_mb || 0);
    }).catch(error => { const text = readableError(error); setNotice(text); addLog("error", `Khởi động: ${text}`); });
    return () => off?.();
  }, [call, addLog]);
  // Model list of the chosen AI, loaded quietly so the dropdown and the cheap backups are ready.
  const loadModels = useCallback(async (name: string) => {
    const data = await call<Data>("list_models", { provider: name });
    setModels(data.models || []);
  }, [call]);
  useEffect(() => {
    setModels([]);
    if (window.kv) loadModels(state.provider).catch(() => undefined);
  }, [state.provider, loadModels]);
  useEffect(() => {
    if (step !== "look" || Object.keys(gallery).length || !window.kv) return;
    call<Data>("gallery").then(data => setGallery(data.thumbnails || {})).catch(error => setNotice(error.message));
  }, [step, call]);

  // Backups when the chosen Gemini model is overloaded or out of quota: only cheap families, so a failure never
  // silently moves the run to an expensive model (gateway 3.x flash costs about 5x 2.5-flash).
  const fallbacks = state.provider === "ollama" ? [] : models.filter(name =>
    name !== (state.model || "") && (name.startsWith("gemini-2.5-flash") || name.includes("flash-lite")));
  const ai = { provider: state.provider, model: state.model, vision: state.vision_ai, fallback_models: fallbacks };
  const save = async (next: Data, dir = directory) => {
    const result = await call<Data>(dir ? "save_run" : "create_run", dir ? { directory: dir, state: next } : { state: next });
    setDirectory(result.directory); setState(result.state); return result;
  };
  const operate = async (method: string, next: Data = state, extras: Data = {}) => {
    const result = await call<Data>(method, { directory, state: next, ...ai, ...extras });
    if (result.state) setState(result.state);
    warn(result.warnings);
    return result;
  };
  const loadStorage = useCallback(() => {
    if (!window.kv) return;
    call<Data>("storage_usage").then(data => setStorage({ total: data.total || 0, folders: data.folders || [] })).catch(() => undefined);
  }, [call]);
  // Refresh after every task, since renders, caches and deletes all change the sizes.
  useEffect(() => { if (!busy) loadStorage(); }, [busy, loadStorage]);
  const refreshRuns = async () => { const result = await call<Data>("list_runs"); setRuns(result.runs || []); };
  const start = (newKind: Kind, newMode: Mode) => {
    setKind(newKind); setMode(newMode); setReached(0); setStepIndex(0); setDirectory("");
    setState({ ...defaults, kind: newKind, auto: newMode === "auto" });
    setRender({ ...renderDefaults }); setTopics([]); setSourceCandidates([]); setSelectedScene(0);
    setInputType("keywords"); setPreviewPath(""); setNotice("");
  };
  // Leaves the open project as it is on disk and returns to the "Bạn muốn tạo video từ đâu?" screen.
  const newVideo = () => {
    setKind(null); setMode(null); setReached(0); setStepIndex(0); setDirectory("");
    setState({ ...defaults }); setRender({ ...renderDefaults }); setTopics([]); setSourceCandidates([]);
    setSelectedScene(0); setInputType("keywords"); setPreviewPath(""); setOutlineText(""); setNotice("");
    setTab("create");
  };
  const openRun = (entry: Data) => work("Mở dự án", async () => {
    const result = await call<Data>("open_run", { directory: entry.directory });
    const saved = result.state || {};
    const newKind: Kind = saved.kind === "clip" ? "clip" : "image";
    const newMode: Mode = saved.auto ? "auto" : "manual";
    setKind(newKind); setMode(newMode); setDirectory(result.directory); setState({ ...defaults, ...saved });
    setSelectedScene(0);
    setRender({ ...renderDefaults, ...(saved.render || {}) });
    setInputType(saved.mode || "keywords"); setTopics(saved.topics || []);
    setSourceCandidates(saved.clip_candidates || []);
    setOutlineText((saved.outline?.points || []).map((v: Data) => `${v.seconds}s | ${v.text}`).join("\n"));
    const flow = stepsFor(newKind, newMode);
    const destination: Step = saved.video ? "finish" : newMode === "auto" ? "look" : saved.scenes ? "scenes" : saved.script || saved.outline ? "script" : "topic";
    const target = Math.max(0, flow.findIndex(item => item.key === destination));
    setReached(target); setStepIndex(target);
    setTab("create"); setNotice("");
  });
  const go = (key: Step) => { const index = steps.findIndex(item => item.key === key); if (index >= 0) setStepIndex(index); };

  const nextContent = () => work("Chuẩn bị nội dung", async () => {
    const input = String(state.input || "").trim();
    if (inputType !== "json" && input.length < (inputType === "keywords" ? 3 : 50)) throw new Error("Hãy nhập nội dung đủ dài để tiếp tục.");
    if (!Number.isInteger(state.duration) || state.duration < 30 || state.duration > 300)
      throw new Error("Thời lượng phải từ 30 đến 300 giây.");
    const base = { ...state, kind, auto: mode === "auto", mode: inputType, input,
      source: inputType.startsWith("source") ? input.slice(0, 15000) : "",
      topic: input.split("\n")[0].slice(0, 90), outline: null, script: null,
      scenes: [], video: null, image_subject: null, clip_source: null };
    if (mode === "auto") {
      if (inputType === "json") {
        const parsed = await call<Data>("parse_json", { text: input });
        const next = { ...base, topic: parsed.script.title, script: parsed.script, outline: parsed.outline?.length ? { title: parsed.script.title, points: parsed.outline } : null, scenes: parsed.scenes || [] };
        setState(next);
      } else setState(base);
      setStepIndex(1); return;
    }
    if (inputType === "keywords") {
      const result = await call<Data>("suggest_topics", { ...ai, input });
      setTopics(result.topics || []); patch({ ...base, topics: result.topics || [] }); go("topic"); return;
    }
    if (inputType === "json") {
      const parsed = await call<Data>("parse_json", { text: input });
      const next = { ...base, topic: parsed.script.title, script: parsed.script, outline: parsed.outline?.length ? { title: parsed.script.title, points: parsed.outline } : null, scenes: parsed.scenes || [] };
      const saved = await save(next); await operate("fit_script", saved.state, { directory: saved.directory }); go("script"); return;
    }
    if (inputType === "source_verbatim") {
      const script = await call<Data>("parse_source", { text: input });
      const saved = await save({ ...base, topic: script.title || base.topic, script });
      await operate("fit_script", saved.state, { directory: saved.directory }); go("script"); return;
    }
    const saved = await save(base);
    const result = await operate("make_outline", saved.state, { directory: saved.directory });
    setOutlineText((result.state.outline?.points || []).map((v: Data) => `${v.seconds}s | ${v.text}`).join("\n"));
    go("script");
  });
  const chooseTopic = () => work("Lập đề cương", async () => {
    if (String(state.topic || "").trim().length < 3) throw new Error("Hãy chọn hoặc nhập chủ đề.");
    const saved = await save({ ...state, topic: state.topic.trim(), topics });
    const result = await operate("make_outline", saved.state, { directory: saved.directory });
    setOutlineText((result.state.outline?.points || []).map((v: Data) => `${v.seconds}s | ${v.text}`).join("\n"));
    go("script");
  });
  const makeScript = () => work("Viết kịch bản", async () => {
    if (!directory) throw new Error("Hãy chọn chủ đề trước.");
    const saved = await save(state);
    const outlined = state.outline?.points?.length
      ? await operate("update_outline", saved.state, { text: outlineText }) : saved;
    await operate("write_script", outlined.state);
  });
  const saveOutline = () => work("Lưu đề cương", async () => {
    const saved = await save(state);
    await operate("update_outline", saved.state, { text: outlineText });
  });
  const nextScript = () => work("Chia cảnh", async () => {
    if (!state.script?.title || !state.script?.body) throw new Error("Hãy tạo hoặc hoàn thiện kịch bản trước.");
    const saved = await save(state);
    const fitted = await operate("fit_script", saved.state);
    if (!fitted.state.scenes?.length) await operate("split_scenes", fitted.state);
    setSelectedScene(0);
    go("scenes");
  });
  const nextScenes = () => work("Lưu cảnh", async () => {
    if (!state.scenes?.length) throw new Error("Chưa có cảnh để dựng video.");
    const saved = await save(state);
    if (kind === "image" && saved.state.scenes.some((item: Data) => !item.image?.file))
      await operate("fetch_images", saved.state, { missing_only: true, pollinations: true });
    if (kind === "clip" && !saved.state.clip_source)
      throw new Error("Hãy chọn và phân tích video nguồn trước khi tiếp tục.");
    go("look");
  });
  const goToFinish = () => work("Lưu diện mạo", async () => {
    if (directory) await save({ ...state, render: { ...render, voice: state.voice } });
    go("finish");
  });
  const generate = () => work("Tạo video", async () => {
    let current = state, dir = directory;
    if (!dir) {
      const saved = await save({ ...state, topic: state.topic || state.input.split("\n")[0].slice(0, 90), render: { ...render, voice: state.voice } });
      current = saved.state; dir = saved.directory;
    } else {
      const saved = await save({ ...state, render: { ...render, voice: state.voice } }); current = saved.state;
    }
    const options = { ...render, voice: current.voice };
    const result = await call<Data>(mode === "auto" ? "auto_generate" : "render_video", { directory: dir, state: current, options, ...ai });
    setState(result.state); warn(result.warnings);
    await refreshRuns();
  });
  const preview = () => work("Dựng xem trước", async () => {
    const result = await call<Data>("render_preview", { directory: directory || undefined, template: render.template, transition: render.transition, motion: true });
    setPreviewPath(result.video);
  });
  const exportVideo = () => work("Xuất video", async () => {
    const target = await window.kv!.saveVideo(state.script?.title || state.topic || "video");
    if (target) {
      const result = await call<Data>("export_video", { directory, target });
      setNotice(`Đã xuất ${result.files?.length || 0} tệp vào thư mục bạn chọn.`);
    }
  });
  const copyCredits = () => work("Sao chép ghi nguồn", async () => {
    const result = await call<Data>("get_credits", { directory });
    if (!result.text) throw new Error("Video này không có ghi nguồn clip.");
    await window.kv!.copyText(result.text);
    setNotice("Đã sao chép ghi nguồn clip.");
  });
  const changeLogo = (index: number, axis: number, value: number) => {
    const logos = (state.clip_source?.logos || []).map((box: number[]) => [...box]);
    logos[index][axis] = Math.max(0, Math.min(1, value));
    patch({ clip_source: { ...state.clip_source, logos } });
  };
  const saveLogos = () => work("Lưu vùng logo", async () => {
    const saved = await save(state);
    await operate("set_logos", saved.state, { logos: state.clip_source?.logos || [] });
  });
  const useTemplate = (key: string, transition?: string) => { patchRender(transition ? { template: key, transition } : { template: key }); setPreviewPath(""); setKind(previous => previous || "image"); setMode(previous => previous || "auto"); setTab("create"); setStepIndex(kind && mode ? stepsFor(kind, mode).findIndex(item => item.key === "look") : 0); };
  const scene = state.scenes?.[selectedScene] || {};
  const scenePath = (item: Data) => item.clip?.thumb ? `${directory}/assets/clip_shots/${item.clip.thumb}` : item.image?.file ? `${directory}/assets/${item.image.file}` : "";

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark"><Icon name="play" size={19}/></span><div><strong>Knowledge<span>Video</span></strong><small>STUDIO</small></div></div>
      <div className="sidebar-section-label">WORKSPACE</div>
      <nav className="side-nav" aria-label="Điều hướng chính">
        {([ ["create", "Tạo video", "spark"], ["history", "Lịch sử video", "clock"], ["templates", "Thư viện mẫu", "layers"], ["settings", "Cài đặt", "settings"] ] as const).map(([key, label, icon]) =>
          <button key={key} className={`side-item ${tab === key ? "active" : ""}`} onClick={() => { if (key === "create" && !directory && !String(state.input || "").trim()) { newVideo(); return; } setTab(key); setNotice(""); if (key === "history") refreshRuns().catch(e => setNotice(e.message)); if (key === "templates" && !Object.keys(gallery).length) work("Đang tải mẫu", async () => { const data = await call<Data>("gallery"); setGallery(data.thumbnails || {}); }); }}><Icon name={icon} size={19}/><span>{label}</span>{key === "create" && <span className="side-plus">+</span>}</button>
        )}
      </nav>
      <div className="sidebar-bottom">{storage && <div className="storage-box"><div className="storage-head"><strong>Dung lượng output</strong><button className="storage-refresh" title="Tính lại" disabled={busy} onClick={loadStorage}>⟳</button></div><div className="storage-total">{formatBytes(storage.total)}<span>{storage.folders.length} thư mục</span></div><div className="storage-list">{storage.folders.length ? storage.folders.map(item => <div key={item.name} className="storage-row" title={item.name || "Tệp nằm ngay trong output"}><div className="storage-row-text"><span>{folderLabel(item.name)}</span><b>{formatBytes(item.bytes)}</b></div><div className="storage-bar"><i style={{ width: `${storage.total ? Math.max(2, item.bytes / storage.total * 100) : 0}%` }}/></div></div>) : <p className="storage-empty">Thư mục output đang trống.</p>}</div></div>}<div className="sidebar-help"><span className="help-icon"><Icon name="spark" size={16}/></span><strong>Từ ý tưởng đến video</strong><p>Biên tập video kiến thức theo cách của bạn.</p></div><div className="sidebar-version">KnowledgeVideo · Desktop</div></div>
    </aside>

    <main className="main">
      <header className="topbar"><div className="breadcrumbs"><span>Workspace</span><span className="slash">/</span><strong>{{ create: "Tạo video", history: "Lịch sử video", templates: "Thư viện mẫu", settings: "Cài đặt" }[tab]}</strong></div><div className="top-actions"><button className={`log-toggle ${logOpen ? "active" : ""}`} onClick={() => setLogOpen(open => !open)}><Icon name="layers" size={15}/> Nhật ký{errorCount > 0 ? <span className="log-badge error">{errorCount}</span> : warnCount > 0 ? <span className="log-badge warn">{warnCount}</span> : null}</button><span className="status-dot"/> <span>Ứng dụng trên máy</span></div></header>
      <div className="scroll-area"><div className="content">
        {notice && <div className="notice"><span>{notice}</span><button onClick={() => setNotice("")}>×</button></div>}
        {tab === "create" && <>
          {!kind && <><div className="page-heading"><div className="eyebrow">BẮT ĐẦU DỰ ÁN MỚI</div><h1>Bạn muốn tạo video từ đâu?</h1><p>Chọn chất liệu chính. Các bước tiếp theo sẽ được sắp theo đúng quy trình bạn chọn.</p></div><div className="choice-grid two">
            <button className="choice-card hero-choice" onClick={() => setKind("image")}><div className="choice-visual image-visual"><div className="visual-photo one"/><div className="visual-photo two"/><span className="visual-badge"><Icon name="image" size={21}/></span></div><span className="choice-number">01 / VIDEO ẢNH</span><h2>Tạo video từ hình ảnh</h2><p>Mỗi cảnh dùng một ảnh tư liệu hoặc ảnh AI, chuyển động nhẹ theo lời kể.</p><span className="choice-link">Chọn video ảnh <Icon name="arrow" size={18}/></span></button>
            <button className="choice-card hero-choice" onClick={() => setKind("clip")}><div className="choice-visual clip-visual"><div className="clip-frame"><Icon name="play" size={42}/></div><div className="film-strips">▣ ▣ ▣ ▣ ▣ ▣ ▣</div><span className="visual-badge"><Icon name="film" size={21}/></span></div><span className="choice-number">02 / VIDEO CLIP</span><h2>Tạo video từ clip</h2><p>Cắt shot từ video nguồn, dựng khung dọc và lồng giọng kể của bạn.</p><span className="choice-link">Chọn video clip <Icon name="arrow" size={18}/></span></button>
          </div></>}
          {kind && !mode && <><div className="page-heading"><button className="text-back" onClick={() => setKind(null)}><Icon name="back" size={16}/> Chọn lại chất liệu</button><div className="eyebrow">{kind === "image" ? "VIDEO ẢNH" : "VIDEO CLIP"} / CÁCH THỰC HIỆN</div><h1>Bạn muốn làm theo cách nào?</h1><p>Cùng một video đích, hai cách điều khiển quá trình tạo.</p></div><div className="choice-grid two mode-grid">
            <button className="choice-card mode-choice" onClick={() => start(kind, "auto")}><span className="mode-icon purple"><Icon name="spark" size={27}/></span><span className="mode-tag">NHANH GỌN</span><h2>Tự động</h2><p>Chọn nội dung và diện mạo trước. Ứng dụng sẽ viết, chọn cảnh và dựng video liên tục.</p><div className="mini-steps">Nội dung <span>→</span> {kind === "clip" ? "Video nguồn → " : ""}Diện mạo <span>→</span> Tạo video</div><span className="choice-link">Bắt đầu tự động <Icon name="arrow" size={18}/></span></button>
            <button className="choice-card mode-choice" onClick={() => start(kind, "manual")}><span className="mode-icon orange"><Icon name="layers" size={27}/></span><span className="mode-tag">KIỂM SOÁT CHI TIẾT</span><h2>Làm thủ công</h2><p>Duyệt chủ đề, sửa kịch bản và từng cảnh trước khi dựng video.</p><div className="mini-steps">Nội dung <span>→</span> Kịch bản <span>→</span> Cảnh <span>→</span> Diện mạo</div><span className="choice-link">Bắt đầu thủ công <Icon name="arrow" size={18}/></span></button>
          </div></>}
          {kind && mode && <><div className="workflow-top"><div><button className="text-back" onClick={() => { setMode(null); setDirectory(""); }}><Icon name="back" size={15}/> Đổi quy trình</button><div className="eyebrow">{kind === "image" ? "VIDEO ẢNH" : "VIDEO CLIP"} <span className="dot-sep">·</span> {mode === "auto" ? "TỰ ĐỘNG" : "THỦ CÔNG"}</div><h1>{steps[stepIndex]?.title}</h1><p>{step === "content" ? "Thiết lập câu chuyện và giọng kể cho video của bạn." : step === "look" ? "Xem thử và chốt diện mạo trước khi tạo video." : step === "finish" ? "Mọi thứ đã sẵn sàng để dựng video." : "Hoàn thiện bước này để đi tiếp."}</p></div><div className="workflow-top-actions">{directory && <button className="secondary small" disabled={busy} onClick={newVideo}><Icon name="spark" size={16}/> Tạo video mới</button>}<span className="step-count">BƯỚC {stepIndex + 1} / {steps.length}</span></div></div>
            <div className="timeline" role="navigation" aria-label="Các bước tạo video">{steps.map((item, i) => <button key={item.key} disabled={busy || i > reached} className={`timeline-item ${i === stepIndex ? "current" : ""} ${i < stepIndex || (i !== stepIndex && i <= reached) ? "done" : ""}`} onClick={() => setStepIndex(i)}><span className="timeline-dot">{i < stepIndex ? <Icon name="check" size={13}/> : String(i + 1).padStart(2, "0")}</span><span>{item.title}</span></button>)}</div>
            {step === "content" && <div className="work-grid"><div className="stack">
              <div className="flow-note"><span>{flowNotes[`${kind}-${mode}`][0]}</span><p>{flowNotes[`${kind}-${mode}`][1]}</p></div>
              <Card title="Nguồn nội dung" description="Chọn cách đưa câu chuyện vào video."><div className="tab-pills">{([ ["keywords", "Từ khóa"], ["source_ai", "Tài liệu + AI"], ["source_verbatim", "Nguyên văn"], ["json", "Kịch bản JSON"] ] as const).map(([value, label]) => <Pill key={value} active={inputType === value} onClick={() => setInputType(value)}>{label}</Pill>)}</div>
                <Field label={inputType === "keywords" ? "Chủ đề hoặc từ khóa" : inputType === "json" ? "Dán JSON kịch bản" : "Nội dung tài liệu"} hint={inputType === "source_verbatim" ? "Lời đọc được giữ theo nội dung bạn đưa vào." : inputType === "source_ai" ? "AI viết kịch bản dựa theo tài liệu này." : undefined}><textarea rows={inputType === "keywords" ? 4 : 9} value={state.input || ""} onChange={e => patch({ input: e.target.value })} placeholder={inputType === "keywords" ? "Ví dụ: Chiến dịch Điện Biên Phủ 1954" : inputType === "json" ? '{"title":"...","hook":"...","paragraphs":["..."]}' : "Dán nội dung hoặc mở tài liệu..."}/></Field>
                {(inputType.startsWith("source") || inputType === "json") && <button className="secondary small" onClick={() => work("Đọc tài liệu", async () => { const path = await window.kv!.chooseFile(inputType === "json" ? "script" : "document"); if (path) { const result = await call<Data>("load_document", { path }); patch({ input: result.text }); } })}><Icon name="folder" size={16}/> Mở file {inputType === "json" ? "JSON" : "tài liệu"}</button>}
              </Card>
              <Card title="Câu chuyện & giọng kể" description="Các thiết lập này được dùng xuyên suốt video."><div className="form-grid">
                <Field label="Thời lượng mục tiêu"><input type="number" min={30} max={300} value={state.duration} onChange={e => patch({ duration: Number(e.target.value) })}/><span className="field-hint">Từ 30 đến 300 giây</span></Field>
                <Field label="Giọng đọc"><Select value={state.voice} onChange={v => patch({ voice: v })} options={Object.entries(catalog.voices || { "vi-VN-HoaiMyNeural": "Hoài My", "vi-VN-NamMinhNeural": "Nam Minh" })}/></Field>
                <Field label="Phong cách lời kể"><Select value={state.style} onChange={v => patch({ style: v })} options={Object.entries(catalog.styles || { ke_chuyen: "Kể chuyện hấp dẫn" })}/></Field>
                <Field label="Số ý chính"><Select value={state.points ?? ""} onChange={v => patch({ points: v ? Number(v) : null })} options={[["", "Tự động"], ...Array.from({ length: 8 }, (_, i) => [String(i + 1), `${i + 1} ý`] as [string, string])]}/></Field>
                <Field label="Số cảnh"><Select value={state.scene_choice} onChange={v => patch({ scene_choice: /^\d+$/.test(v) ? Number(v) : v })} options={Object.entries(catalog.scene_choices || { auto: "Tự động", points: "Theo số ý chính" })}/></Field>
                <Field label="AI viết nội dung"><Select value={state.provider} onChange={v => patch({ provider: v, model: "" })} options={[["ollama", "Ollama trên máy"], ["gemini", "Gemini"], ["gateway", "Gemini qua gateway"]]}/></Field>
                <Field label="Model" hint={fallbacks.length ? `Dự phòng khi lỗi: ${fallbacks.slice(0, 3).join(", ")}${fallbacks.length > 3 ? "…" : ""}` : undefined}><div className="input-action">{models.length ? <Select value={state.model || ""} onChange={v => patch({ model: v })} options={[["", "Mặc định (theo Cài đặt)"], ...(state.model && !models.includes(state.model) ? [[state.model, state.model] as [string, string]] : []), ...models.map(name => [name, name] as [string, string])]}/> : <input value={state.model || ""} onChange={e => patch({ model: e.target.value })} placeholder="Mặc định (theo Cài đặt)"/>}<button title="Tải lại danh sách model" onClick={() => work("Tải danh sách model", () => loadModels(state.provider))}><Icon name="refresh" size={17}/></button></div></Field>
                {kind === "clip" && <Field label="AI xem khung hình"><Select value={state.vision_ai} onChange={v => patch({ vision_ai: v })} options={[["same", "Cùng AI viết nội dung"], ["ollama", "Ollama"], ["gemini", "Gemini"], ["gateway", "Gateway"]]}/></Field>}
              </div></Card>
            </div><aside className="context-panel"><div className="context-icon"><Icon name={kind} size={22}/></div><h3>{kind === "image" ? "Video ảnh" : "Video clip"}</h3><p>{kind === "image" ? "Ảnh sẽ được chuẩn bị cho từng cảnh sau khi kịch bản hoàn tất." : "Bạn có thể dán link YouTube hoặc để ứng dụng tìm video nguồn."}</p><div className="context-rule"/><span>QUY TRÌNH</span><strong>{mode === "auto" ? "Tự động" : "Thủ công"}</strong><span>SỐ BƯỚC</span><strong>{steps.length} bước</strong></aside></div>}
            {step === "topic" && <div className="stack"><Card title="Chọn góc kể" description="AI đã gợi ý từ nội dung bạn nhập. Bạn có thể chọn hoặc sửa lại."><div className="topic-grid">{topics.map((item, i) => <button key={i} className={`topic-card ${state.topic === item.title ? "selected" : ""}`} onClick={() => patch({ topic: item.title })}><span>0{i + 1}</span><h3>{item.title}</h3><p>{item.angle}</p></button>)}</div><Field label="Chủ đề cuối cùng"><input value={state.topic || ""} onChange={e => patch({ topic: e.target.value })}/></Field></Card></div>}
            {step === "script" && <div className="stack"><Card title="Đề cương" description="Duyệt các ý chính trước khi tạo lời đọc.">{state.outline?.points?.length ? <div className="outline-list">{state.outline.points.map((point: Data, i: number) => <div key={i}><span>{String(i + 1).padStart(2, "0")}</span><p>{point.text}</p><em>{point.seconds}s</em></div>)}</div> : <p className="muted">Kịch bản này không có đề cương riêng.</p>}<div className="outline-edit"><Field label={"Ch\u1ec9nh \u0111\u1ec1 c\u01b0\u01a1ng (m\u1ed7i d\u00f2ng: 20s | \u00fd ch\u00ednh)"}><textarea rows={6} value={outlineText} onChange={e => setOutlineText(e.target.value)}/></Field><button className="secondary small" disabled={busy || !state.outline?.points?.length} onClick={saveOutline}>{"L\u01b0u \u0111\u1ec1 c\u01b0\u01a1ng"}</button></div></Card><Card title="Lời đọc" description="Tạo với AI rồi chỉnh từng phần nếu cần."><div className="script-actions"><button className="secondary" disabled={busy || !state.outline?.points?.length} onClick={makeScript}><Icon name="spark" size={17}/> {state.script ? "Viết lại bằng AI" : "Tạo kịch bản bằng AI"}</button>{state.script && <button className="secondary" disabled={busy} onClick={() => work("Đo lại lời đọc", async () => { const saved = await save(state); await operate("fit_script", saved.state); })}><Icon name="volume" size={17}/> Đo lại thời lượng</button>}</div>{state.script && <div className="stack"><Field label="Tiêu đề"><input value={state.script.title || ""} onChange={e => patch({ script: { ...state.script, title: e.target.value } })}/></Field><Field label="Mở đầu"><textarea rows={3} value={state.script.hook || ""} onChange={e => patch({ script: { ...state.script, hook: e.target.value } })}/></Field><Field label="Nội dung"><textarea rows={10} value={state.script.body || ""} onChange={e => patch({ script: { ...state.script, body: e.target.value } })}/></Field><div className="info-line">{state.script.timing?.seconds ? `Lời đọc dự kiến: ${Math.round(state.script.timing.seconds)} giây` : "Đo lại sau khi sửa lời đọc."}</div></div>}</Card></div>}
            {step === "source" && <div className="stack"><Card title="Chọn video nguồn" description="Dán link YouTube hoặc để ứng dụng tìm khi tạo video."><div className="form-grid"><Field label="Link YouTube"><input value={state.clip_link || ""} onChange={e => patch({ clip_link: e.target.value })} placeholder="https://www.youtube.com/watch?v=..."/></Field><Field label="Từ khóa tìm kiếm"><input value={state.clip_query || ""} onChange={e => patch({ clip_query: e.target.value })} placeholder="Để trống: tự lấy từ chủ đề"/></Field><Field label="Bộ lọc nội dung"><Select value={state.clip_filter} onChange={v => patch({ clip_filter: v })} options={Object.entries(catalog.clip_filters || { real: "Cảnh quay thực" })}/></Field></div><div className="info-line">Nếu để trống link, ứng dụng sẽ tìm video phù hợp với chủ đề.</div></Card></div>}
            {step === "scenes" && <div className="stack"><Card title={kind === "image" ? "Ảnh cho từng cảnh" : "Shot cho từng cảnh"} description={`${state.scenes?.length || 0} cảnh từ kịch bản. Chọn một cảnh để xem và chỉnh.`}><div className="scene-toolbar">{kind === "image" ? <button className="secondary" disabled={busy} onClick={() => work("Chuẩn bị ảnh", async () => { const result = await operate("fetch_images", state, { missing_only: true, pollinations: true }); setState(result.state); })}><Icon name="image" size={17}/> Tìm ảnh cho các cảnh</button> : <><button className="secondary" disabled={busy} onClick={() => work("Tìm video nguồn", async () => { const result = await call<Data>("search_clips", { ...ai, query: state.clip_query || state.video_query?.vi || state.topic, filter: state.clip_filter, about: state.topic }); setSourceCandidates(result.candidates || []); })}><Icon name="spark" size={17}/> Tìm video</button><button className="secondary" disabled={busy || !state.clip_source} onClick={() => work("Ghép lại shot", async () => { await operate("reassign_clips"); })}><Icon name="refresh" size={17}/> Ghép lại shot</button></>}</div>{kind === "clip" && <div className="source-inline"><Field label="Link YouTube"><input value={state.clip_link || ""} onChange={e => patch({ clip_link: e.target.value })} placeholder="Dán link video nguồn"/></Field><button className="primary" disabled={busy || !state.clip_link} onClick={() => work("Phân tích video nguồn", async () => { const saved = await save(state); await operate("prepare_clips", saved.state, { video: state.clip_link }); })}>Phân tích video</button></div>}{kind === "clip" && sourceCandidates.length > 0 && <div className="candidate-list">{sourceCandidates.slice(0, 8).map((item, i) => <div key={i} className="candidate"><div><strong>{item.title || item.id}</strong><p>{item.channel || ""} · {item.score ?? ""} điểm</p></div><button className="secondary small" onClick={() => window.kv?.openExternal(`https://www.youtube.com/watch?v=${item.id}`)}><Icon name="link" size={14}/></button><button className="secondary small" disabled={busy || item.allowed === false} onClick={() => work("Phân tích video nguồn", async () => { const saved = await save({ ...state, clip_link: item.id }); await operate("prepare_clips", saved.state, { video: item.id }); })}>Dùng video này</button></div>)}</div>}
              <div className="scene-grid">{(state.scenes || []).map((item: Data, i: number) => <button key={i} className={`scene-card ${selectedScene === i ? "selected" : ""}`} onClick={() => setSelectedScene(i)}><div className="scene-thumb"><LocalMedia path={scenePath(item)}/><span>{String(i + 1).padStart(2, "0")}</span></div><p>{item.text || `Cảnh ${i + 1}`}</p></button>)}</div></Card>{kind === "clip" && state.clip_source && <Card title={"V\u00f9ng logo / watermark"} description={"Ch\u1ec9nh c\u00e1c v\u00f9ng c\u1ea7n l\u00e0m m\u1edd trong video."}><div className="logo-layout"><div className="logo-preview"><LocalMedia path={state.clip_source.shots?.[0]?.thumb ? `${directory}/assets/clip_shots/${state.clip_source.shots[0].thumb}` : ""}/>{(state.clip_source.logos || []).map((box: number[], i: number) => <span key={i} className="logo-box" style={{left:`${box[0]*100}%`,top:`${box[1]*100}%`,width:`${box[2]*100}%`,height:`${box[3]*100}%`}}/>)}</div><div className="logo-fields">{(state.clip_source.logos || []).map((box: number[], i: number) => <div className="logo-row" key={i}><strong>Logo {i+1}</strong>{box.map((value, axis) => <label key={axis}>{["X","Y","W","H"][axis]}<input type="number" min="0" max="1" step="0.01" value={value} onChange={e => changeLogo(i,axis,Number(e.target.value))}/></label>)}<button className="secondary small" onClick={() => patch({clip_source:{...state.clip_source,logos:state.clip_source.logos.filter((_: number[], n: number) => n!==i)}})}>{"\u00d7"}</button></div>)}<div className="button-row"><button className="secondary small" onClick={() => patch({clip_source:{...state.clip_source,logos:[...(state.clip_source.logos || []),[0.75,0.02,0.2,0.1]]}})}>{"Th\u00eam v\u00f9ng"}</button><button className="secondary small" onClick={() => patch({clip_source:{...state.clip_source,logos:[]}})}>{"Kh\u00f4ng c\u00f3 logo"}</button><button className="primary small" disabled={busy} onClick={saveLogos}>{"L\u01b0u v\u00f9ng logo"}</button></div></div></div></Card>}{state.scenes?.length > 0 && <Card title={`Cảnh ${selectedScene + 1}`} description="Chỉnh nội dung và hình của cảnh đang chọn."><div className="scene-detail"><LocalMedia path={scenePath(scene)} className="detail-media"/><div className="stack"><Field label="Lời đọc của cảnh"><textarea rows={5} value={scene.text || ""} onChange={e => { const scenes = [...state.scenes]; scenes[selectedScene] = { ...scene, text: e.target.value }; patch({ scenes }); }}/></Field><Field label="Từ khóa ảnh"><input value={scene.image_query_vi || ""} onChange={e => { const scenes = [...state.scenes]; scenes[selectedScene] = { ...scene, image_query_vi: e.target.value }; patch({ scenes }); }}/></Field>{kind === "image" ? <div className="button-row"><button className="secondary small" disabled={busy} onClick={() => work("Đổi ảnh", async () => { const saved = await save(state); await operate("replace_image", saved.state, { index: selectedScene, variant: "wikimedia" }); })}>Ảnh khác</button><button className="secondary small" disabled={busy} onClick={() => work("Tạo ảnh AI", async () => { const saved = await save(state); await operate("replace_image", saved.state, { index: selectedScene, variant: "gemini" }); })}>Ảnh AI Gemini</button><button className="secondary small" disabled={busy} onClick={() => work("Pollinations", async () => { const saved = await save(state); await operate("replace_image", saved.state, { index: selectedScene, variant: "pollinations" }); })}>{"\u1ea2nh Pollinations"}</button></div> : <div className="button-row"><button className="secondary small" disabled={busy} onClick={() => work("Dùng ảnh", async () => { await operate("use_picture", state, { index: selectedScene }); })}>Dùng ảnh thay clip</button>{state.clip_source?.shots?.length > 0 && <Select value={scene.clip?.shot ?? ""} onChange={v => work("Chọn shot", async () => { await operate("choose_shot", state, { index: selectedScene, shot: Number(v) }); })} options={state.clip_source.shots.map((shot: Data, i: number) => [String(i), `Shot ${i + 1} · ${Math.round(shot.start || 0)}s`])}/>}</div>}</div></div></Card>}</div>}
            {step === "look" && <div className="stack"><Card title="Chọn template" description="Chọn bằng thẻ hình. Mẫu sẽ áp dụng cho toàn bộ video."><div className="template-grid">{Object.entries(catalog.templates || { "history-scroll": "Cổ thư", "history-imperial": "Hoàng triều", "history-archive": "Tư liệu" }).map(([key, label]) => <button key={key} className={`template-card ${render.template === key ? "selected" : ""}`} onClick={() => { patchRender({ template: key }); setPreviewPath(""); }}><div className={`template-art ${templateNotes[key]?.[2] || "scroll"}`}>{gallery[key] ? <LocalMedia path={gallery[key]}/> : <><span>CHUYỆN LỊCH SỬ</span><strong>{templateNotes[key]?.[0] || String(label)}</strong><i>01 / 03</i></>}</div><div className="template-card-bottom"><strong>{String(label)}</strong><p>{templateNotes[key]?.[1]}</p></div><span className="template-check"><Icon name="check" size={13}/></span></button>)}</div></Card>
              <Card title="Chuyển cảnh" description="Chọn hiệu ứng theo nhịp kể của video."><div className="effect-grid">{Object.entries(transitionNotes).map(([key, label]) => <button key={key} className={`effect-card ${render.transition === key ? "selected" : ""}`} onClick={() => { patchRender({ transition: key }); setPreviewPath(""); }}><div className={`effect-visual effect-${key}`}><span/><span/></div><strong>{label as string}</strong></button>)}</div></Card>
              <Card title="Chữ trên video" description="Kiểu hiển thị lời đọc, xem thử ngay trên thẻ."><div className="caption-grid">{([ ["highlight", "Chạy theo từng từ", "Một từ sáng lên theo lời đọc"], ["normal", "Phụ đề tĩnh", "Hiện cả câu ở cuối khung hình"], ["off", "Không hiện chữ", "Chỉ giữ hình và giọng đọc"] ] as const).map(([key, title, desc]) => <button key={key} className={`caption-card ${render.subtitle_style === key ? "selected" : ""}`} onClick={() => patchRender({ subtitle_style: key })}><div className="caption-preview">{key !== "off" && <span>Ngày ấy, <b className={key === "highlight" ? "word-active" : ""}>lịch sử</b> đã đổi thay</span>}</div><strong>{title}</strong><p>{desc}</p></button>)}</div></Card>
              <Card title="Xuất video" description="Các lựa chọn kỹ thuật dùng khi dựng MP4."><div className="form-grid"><Field label="Thời gian cảnh"><Select value={render.scene_timing} onChange={v => patchRender({ scene_timing: v })} options={Object.entries(catalog.scene_timings || { sentences: "Theo câu đọc", even: "Chia đều" })}/></Field><Field label="Độ phân giải"><Select value={render.resolution} onChange={v => patchRender({ resolution: v })} options={(catalog.resolutions || ["1080x1920", "720x1280"]).map((v: string) => [v, v])}/></Field><Field label="Nhạc nền"><div className="input-action"><input readOnly value={render.music_source || ""} placeholder="Không dùng nhạc"/><button onClick={() => window.kv?.chooseFile("music").then(v => v && patchRender({ music_source: v }))}><Icon name="folder" size={17}/></button></div></Field><Field label={`Âm lượng nhạc · ${render.music_volume}%`}><input type="range" min="0" max="100" value={render.music_volume} onChange={e => patchRender({ music_volume: Number(e.target.value) })}/></Field></div></Card>
              <Card title="Xem thử" description="Xem chuyển cảnh và bố cục mẫu trước khi tạo video."><div className="preview-box">{previewPath ? <LocalMedia path={previewPath} video className="preview-video"/> : <div className={`preview-placeholder ${templateNotes[render.template]?.[2] || "scroll"}`}><span>XEM TRƯỚC · 9:16</span><strong>{state.script?.title || state.topic || "CÂU CHUYỆN LỊCH SỬ"}</strong><small>{transitionNotes[render.transition]} · {render.subtitle_style === "highlight" ? "Chạy theo từng từ" : render.subtitle_style === "normal" ? "Phụ đề tĩnh" : "Không phụ đề"}</small></div>}</div><button className="secondary" disabled={busy} onClick={preview}><Icon name="play" size={17}/> Dựng video xem thử</button></Card>
            </div>}
            {step === "finish" && <div className="finish-grid"><Card title={state.video ? "Video đã hoàn thành" : "Sẵn sàng tạo video"} description={state.video ? "Xem và xuất video của bạn." : "Kiểm tra nhanh lựa chọn cuối cùng."}><div className="summary-list"><div><span>Chất liệu</span><strong>{kind === "image" ? "Ảnh" : "Clip"}</strong></div><div><span>Quy trình</span><strong>{mode === "auto" ? "Tự động" : "Thủ công"}</strong></div><div><span>Thời lượng</span><strong>{state.duration} giây</strong></div><div><span>Giọng đọc</span><strong>{catalog.voices?.[state.voice] || state.voice}</strong></div><div><span>Template</span><strong>{catalog.templates?.[render.template] || render.template}</strong></div><div><span>Chuyển cảnh</span><strong>{transitionNotes[render.transition]}</strong></div><div><span>Phụ đề</span><strong>{catalog.subtitle_styles?.[render.subtitle_style] || render.subtitle_style}</strong></div></div>{state.video ? <div className="button-row"><button className="primary" onClick={exportVideo}><Icon name="upload" size={17}/> Xuất MP4</button><button className="secondary" onClick={() => window.kv?.openPath(directory)}><Icon name="folder" size={17}/> Mở thư mục</button><button className="secondary" disabled={busy} onClick={generate}><Icon name="refresh" size={17}/>{"D\u1ef1ng l\u1ea1i"}</button>{kind === "clip" && <button className="secondary" onClick={copyCredits}><Icon name="link" size={17}/>{"Copy ghi ngu\u1ed3n"}</button>}</div> : <button className="primary generate-button" disabled={busy} onClick={generate}><Icon name="play" size={19}/> Tạo video</button>}</Card><div className="result-preview">{state.video ? <LocalMedia path={state.video} video className="result-video"/> : <div className={`result-placeholder ${templateNotes[render.template]?.[2] || "scroll"}`}><span>KNOWLEDGEVIDEO</span><strong>{state.script?.title || state.topic || "Video của bạn"}</strong><span>9:16 · {render.resolution}</span></div>}</div></div>}
            {step !== "finish" && <div className="workflow-footer"><button className="secondary" disabled={busy || stepIndex === 0} onClick={() => setStepIndex(i => Math.max(0, i - 1))}><Icon name="back" size={16}/> Quay lại</button><span>{directory ? "Dự án đã lưu trong output" : "Bạn có thể điều chỉnh ở bước tiếp theo"}</span><button className="primary" disabled={busy} onClick={step === "content" ? nextContent : step === "topic" ? chooseTopic : step === "script" ? nextScript : step === "scenes" ? nextScenes : step === "look" ? goToFinish : () => setStepIndex(i => i + 1)}>Tiếp tục <Icon name="arrow" size={17}/></button></div>}
          </>}
        </>}
        {tab === "history" && <><div className="page-heading"><div className="eyebrow">DỰ ÁN CỦA BẠN</div><h1>Lịch sử video</h1><p>Mở lại để sửa, dựng tiếp hoặc xuất video đã hoàn thành.</p></div><div className="history-list">{runs.length ? runs.map((entry, i) => { const saved = entry.state || {}; return <button className="history-row" key={entry.directory || i} onClick={() => openRun(entry)}><div className="history-thumb"><LocalMedia path={saved.scenes?.[0]?.clip?.thumb ? `${entry.directory}/assets/clip_shots/${saved.scenes[0].clip.thumb}` : saved.scenes?.[0]?.image?.file ? `${entry.directory}/assets/${saved.scenes[0].image.file}` : ""}/></div><div className="history-info"><span>{saved.kind === "clip" ? "VIDEO CLIP" : "VIDEO ẢNH"} · {saved.duration || "?"} GIÂY</span><h3>{saved.script?.title || saved.topic || saved.input || "Dự án mới"}</h3><p>{saved.video ? "Đã hoàn thành" : saved.scenes?.length ? `${saved.scenes.length} cảnh · Đang biên tập` : saved.script ? "Đã có kịch bản" : "Đang chuẩn bị"}</p></div><Icon name="arrow" size={20}/></button>; }) : <Card><div className="empty-state"><Icon name="clock" size={28}/><h3>Chưa có video nào</h3><p>Dự án bạn tạo sẽ xuất hiện ở đây.</p></div></Card>}</div></>}
        {tab === "templates" && <><div className="page-heading"><div className="eyebrow">THƯ VIỆN DIỆN MẠO</div><h1>Mẫu video</h1><p>Xem các template dựng video lịch sử và áp dụng cho dự án.</p></div><div className="gallery-toolbar"><Field label="Chuyển cảnh"><Select value={galleryTransition} onChange={v => { setGalleryTransition(v); setPreviewPath(""); }} options={Object.entries(transitionNotes) as [string, string][]}/></Field></div><div className="gallery-grid">{Object.entries(catalog.templates || {}).map(([key, label]) => <Card key={key} className="gallery-card"><div className={`gallery-art ${templateNotes[key]?.[2] || "scroll"}`}>{gallery[key] ? <LocalMedia path={gallery[key]}/> : <strong>{templateNotes[key]?.[0] || String(label)}</strong>}</div><div className="gallery-info"><h2>{label as string}</h2><p>{templateNotes[key]?.[1]}</p><div className="button-row"><button className="secondary small" disabled={busy} onClick={() => work("Xem trước mẫu", async () => { const data = await call<Data>("render_preview", { template: key, transition: galleryTransition, motion: true }); setPreviewPath(data.video); })}>Xem chuyển động</button><button className="primary small" onClick={() => useTemplate(key, galleryTransition)}>Dùng mẫu</button></div></div></Card>)}</div>{previewPath && <Card title="Xem trước template"><div className="gallery-preview"><LocalMedia path={previewPath} video/></div></Card>}</>}
        {tab === "settings" && <><div className="page-heading"><div className="eyebrow">THIẾT LẬP ỨNG DỤNG</div><h1>Cài đặt</h1><p>AI, nơi lưu video và công cụ dựng trên máy này.</p></div><div className="stack"><Card title="AI & tích hợp"><div className="form-grid settings-grid">{settingFields.slice(0, 10).map(([key, label, type]) => <Field label={label} key={key}><input type={type} value={settings[key] || ""} onChange={e => setSettings(previous => ({ ...previous, [key]: e.target.value }))}/></Field>)}</div></Card><Card title="Lưu trữ & video"><div className="form-grid settings-grid">{settingFields.slice(10).map(([key, label, type]) => <Field label={label} key={key}><div className="input-action"><input type={type} value={settings[key] || ""} onChange={e => setSettings(previous => ({ ...previous, [key]: e.target.value }))}/>{["KV_OUTPUT_DIR", "KV_VIDEO_FONT"].includes(key) && <button onClick={() => (key === "KV_OUTPUT_DIR" ? window.kv?.chooseFolder() : window.kv?.chooseFile("font"))?.then(value => value && setSettings(previous => ({ ...previous, [key]: value })))}><Icon name="folder" size={16}/></button>}</div></Field>)}</div><div className="settings-actions"><span>Cache clip: {cacheMb} MB · Output: {outputDir}</span><button className="secondary" disabled={busy} onClick={() => work("Dọn cache", async () => { const data = await call<Data>("clear_cache"); setCacheMb(data.cache_mb); })}>Dọn cache clip</button><button className="primary" disabled={busy} onClick={() => work("Lưu cài đặt", async () => { const data = await call<Data>("save_settings", { values: settings }); setSettings(data.settings); setOutputDir(data.output_dir); setNotice("Đã lưu cài đặt."); })}>Lưu cài đặt</button></div></Card></div></>}
      </div></div>
      {failure && <div className="error-toast" role="alert"><span className="error-toast-icon">!</span><div><strong>{failure.title} không thành công</strong><p>{failure.text}</p><div className="error-toast-actions"><button onClick={() => { setLogOpen(true); setFailure(null); }}>Xem nhật ký</button><button onClick={() => window.kv?.copyText(`${failure.title}: ${failure.text}`)}>Sao chép</button></div></div><button className="error-toast-close" aria-label="Đóng" onClick={() => setFailure(null)}>×</button></div>}
      {logOpen && <section className="log-panel" aria-label="Nhật ký">
        <header><div><strong>Nhật ký</strong><span>{logs.length} dòng{errorCount ? ` · ${errorCount} lỗi` : ""}{warnCount ? ` · ${warnCount} cảnh báo` : ""}</span></div><div className="log-actions"><button disabled={!logs.length} onClick={() => window.kv?.copyText(logs.map(l => `${clock(l.time)} [${logLabels[l.kind]}] ${l.text}${l.percent >= 0 ? ` (${l.percent}%)` : ""}`).join("\n"))}>Sao chép</button><button disabled={!logs.length} onClick={() => setLogs([])}>Xóa</button><button aria-label="Đóng nhật ký" onClick={() => setLogOpen(false)}>×</button></div></header>
        <div className="log-list">{logs.length ? logs.map(entry => <div key={entry.id} className={`log-row ${entry.kind}`}><time>{clock(entry.time)}</time><span className="log-kind">{logLabels[entry.kind]}</span><p>{entry.text}</p>{entry.kind === "progress" && entry.percent >= 0 && <span className="log-percent">{entry.percent}%</span>}</div>) : <p className="log-empty">Chưa có hoạt động nào. Các bước, cảnh báo và lỗi sẽ hiện ở đây.</p>}<div ref={logEnd}/></div>
      </section>}
      {busy && <div className="busy-bar"><div className="busy-progress" style={{ width: percent >= 0 ? `${Math.max(3, percent)}%` : "35%" }}/><span>{status || "Đang xử lý"}</span>{percent >= 0 && <strong>{percent}%</strong>}<button onClick={() => window.kv?.cancel()}>Hủy</button></div>}
    </main>
  </div>;
}


