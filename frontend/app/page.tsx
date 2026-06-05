"use client";

import { useState, useRef, useEffect } from "react";
import { useTheme } from "./providers";
import "highlight.js/styles/github-dark.css";
import { API_URL, Conversation, Message, ToolCall, FileAttachment } from "./lib/types";
import { apiFetch } from "./lib/api";
import {
  formatRelativeTime,
  groupConversationsByTime,
  getToolLabel,
  getFileType,
  readFileAsDataURL,
  QUICK_COMMANDS,
} from "./lib/utils";
import { MarkdownRenderer } from "./components/markdown";

export default function ChatPage() {
  return <ChatView />;
}

function ChatView() {
  const { theme, toggle } = useTheme();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [selectedModel, setSelectedModel] = useState("qwen-max");
  const [models, setModels] = useState<{key: string; name: string}[]>([]);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [showMemories, setShowMemories] = useState(false);
  const [memories, setMemories] = useState<{id: number; category: string; content: string}[]>([]);
  const [profile, setProfile] = useState<Record<string, string[]>>({});
  const [memTab, setMemTab] = useState<"memories" | "profile">("memories");
  const [recording, setRecording] = useState(false);
  const [sttLoading, setSttLoading] = useState(false);
  const [sttError, setSttError] = useState("");
  const [speaking, setSpeaking] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [showCommands, setShowCommands] = useState(false);
  const [schedTasks, setSchedTasks] = useState<{id: number; name: string; prompt: string; cron: string; enabled: boolean}[]>([]);
  const [newTaskName, setNewTaskName] = useState("");
  const [newTaskPrompt, setNewTaskPrompt] = useState("");
  const [newTaskCron, setNewTaskCron] = useState("0 8 * * *");
  const [customPrompt, setCustomPrompt] = useState("");
  const [toasts, setToasts] = useState<{ id: number; message: string; type: "error" | "success" | "info" }[]>([]);
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const [mobileActionsIdx, setMobileActionsIdx] = useState<number | null>(null);
  const [waveformData, setWaveformData] = useState<number[]>([0, 0, 0, 0, 0]);
  const [suggestions, setSuggestions] = useState<{ icon: string; text: string }[]>([
    { icon: "💡", text: "帮我分析一下今天适合学什么" },
    { icon: "🔍", text: "搜索一下最近的 AI 新闻" },
    { icon: "🎯", text: "聊聊你的能力吧" },
  ]);
  const [searchMode, setSearchMode] = useState<"title" | "content">("title");
  const [searchResults, setSearchResults] = useState<{ conversation_id: number; conversation_title: string; content: string; role: string }[]>([]);
  const [backendVersion, setBackendVersion] = useState("0.5.0");
  const [sidebarWidth, setSidebarWidth] = useState(288);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animFrameRef = useRef<number>(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const voicesLoadedRef = useRef(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const recordingCleanup = useRef<(() => void) | null>(null);

  function showToast(message: string, type: "error" | "success" | "info" = "error") {
    const id = Date.now();
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4000);
  }

  useEffect(() => {
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    const loadVoices = () => { if (window.speechSynthesis.getVoices().length > 0) voicesLoadedRef.current = true; };
    loadVoices();
    window.speechSynthesis.addEventListener("voiceschanged", loadVoices);
    return () => window.speechSynthesis.removeEventListener("voiceschanged", loadVoices);
  }, []);

  useEffect(() => { const s = localStorage.getItem("customPrompt"); if (s) setCustomPrompt(s); }, []);

  // ======== 语音输入 ========

  async function startRecording() {
    if (recording || sttLoading) return;
    setSttError(""); setRecording(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const audioCtx = new AudioContext();
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 32;
      source.connect(analyser);
      analyserRef.current = analyser;
      function updateWaveform() {
        if (!analyserRef.current) return;
        const data = new Uint8Array(analyserRef.current.frequencyBinCount);
        analyserRef.current.getByteFrequencyData(data);
        const bands = [0, 2, 4, 6, 8].map((idx) => data[idx] || 0);
        setWaveformData(bands);
        animFrameRef.current = requestAnimationFrame(updateWaveform);
      }
      updateWaveform();
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus"
        : MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm"
        : MediaRecorder.isTypeSupported("audio/ogg;codecs=opus") ? "audio/ogg;codecs=opus" : "audio/mp4";
      const recorder = new MediaRecorder(stream, { mimeType });
      const chunks: BlobPart[] = [];
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
      recorder.onstop = async () => {
        analyserRef.current = null;
        cancelAnimationFrame(animFrameRef.current);
        setWaveformData([0, 0, 0, 0, 0]);
        stream.getTracks().forEach(t => t.stop()); mediaRecorderRef.current = null; setRecording(false);
        const ext = mimeType.includes("ogg") ? "ogg" : mimeType.includes("mp4") ? "mp4" : "webm";
        const blob = new Blob(chunks, { type: mimeType });
        if (blob.size < 1000) { setSttError("录音太短"); showToast("录音太短，请重试"); return; }
        setSttLoading(true); setSttError("");
        const fd = new FormData(); fd.append("audio", blob, `audio.${ext}`);
        try {
          const res = await apiFetch("/stt", { method: "POST", body: fd });
          const data = await res.json();
          if (data.text) setInput((prev) => prev ? prev + " " + data.text : data.text);
          else setSttError(data.error || data.detail || "识别为空，请重试");
        } catch { setSttError("网络错误"); showToast("语音服务不可用"); }
        setSttLoading(false);
      };
      mediaRecorderRef.current = recorder; recorder.start();
      const timer = setTimeout(() => { if (recorder.state === "recording") recorder.stop(); }, 60000);
      recordingCleanup.current = () => { clearTimeout(timer); if (recorder.state === "recording") recorder.stop(); };
    } catch { setRecording(false); setSttError("无法访问麦克风，请检查浏览器权限"); }
  }

  function stopRecording() { recordingCleanup.current?.(); recordingCleanup.current = null; }
  function toggleRecording() { recording ? stopRecording() : startRecording(); }

  function speak(text: string) {
    if (speaking) { window.speechSynthesis.cancel(); setSpeaking(false); return; }
    const cleanText = text.replace(/!\[.*?\]\(.*?\)/g, "").replace(/\[.*?\]\(.*?\)/g, "").replace(/```[\s\S]*?```/g, "").replace(/[#*_`~]/g, "").slice(0, 500);
    if (!cleanText.trim()) return;
    const u = new SpeechSynthesisUtterance(cleanText); u.lang = "zh-CN"; u.rate = 1.0; u.pitch = 1.1;
    const voices = window.speechSynthesis.getVoices();
    const zh = voices.find(v => v.lang.startsWith("zh") && /female|女|ting/i.test(v.name)) || voices.find(v => v.lang === "zh-CN" && !/male|男/i.test(v.name)) || voices.find(v => v.lang.startsWith("zh"));
    if (zh) u.voice = zh;
    u.onend = () => setSpeaking(false); u.onerror = () => setSpeaking(false);
    window.speechSynthesis.cancel(); setSpeaking(true); window.speechSynthesis.speak(u);
  }

  function stopStreaming() { abortRef.current?.abort(); }

  async function updateConversationTitle(convId: number, title: string) {
    // HF Spaces 代理无法正确转发中文 JSON body，用 query param 绕过
    await apiFetch(`/conversations/${convId}?title=${encodeURIComponent(title)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: "{}" });
    setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, title } : c)));
  }

  useEffect(() => {
    apiFetch("/conversations").then((r) => r.json()).then((d) => { if (Array.isArray(d)) setConversations(d); }).catch(() => {});
    apiFetch("/models").then((r) => r.json()).then((d) => { if (Array.isArray(d) && d.length > 0) { setModels(d); const s = localStorage.getItem("defaultModel"); setSelectedModel(s && d.some(m => m.key === s) ? s : d[0].key); } }).catch(() => {});
    apiFetch("/suggestions").then((r) => r.json()).then((d) => { if (Array.isArray(d) && d.length > 0) setSuggestions(d); }).catch(() => {});
    apiFetch("/").then((r) => r.json()).then((d) => { if (d.version) setBackendVersion(d.version); }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!activeConvId) { setMessages([]); return; }
    apiFetch(`/conversations/${activeConvId}/messages`).then((r) => r.json()).then((msgs) => setMessages(msgs.map((m: Message) => ({ role: m.role, content: m.content, created_at: m.created_at })))).catch(() => showToast("加载消息失败"));
  }, [activeConvId]);

  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }); }, [messages]);

  // 防休眠
  useEffect(() => { const id = setInterval(() => { apiFetch("/").catch(() => {}); }, 10 * 60 * 1000); return () => clearInterval(id); }, []);

  async function createConversation() {
    const res = await apiFetch("/conversations", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    const conv = await res.json(); setConversations((prev) => [conv, ...prev]); setActiveConvId(conv.id); setMessages([]);
  }

  async function deleteConversation(convId: number) {
    setPendingDeleteId(convId);
  }

  async function confirmDeleteConversation() {
    if (!pendingDeleteId) return;
    const convId = pendingDeleteId;
    setPendingDeleteId(null);
    try {
      await apiFetch(`/conversations/${convId}`, { method: "DELETE" });
      setConversations((prev) => prev.filter((c) => c.id !== convId));
      if (activeConvId === convId) { setActiveConvId(null); setMessages([]); }
    } catch { showToast("删除对话失败"); }
  }

  function loadMemories() {
    apiFetch("/memories").then((r) => r.json()).then((d) => { if (Array.isArray(d)) setMemories(d); }).catch(() => showToast("加载记忆失败"));
    apiFetch("/profile").then((r) => r.json()).then((d) => { if (d && typeof d === "object") setProfile(d); }).catch(() => {});
    setShowMemories(true);
  }

  function loadSchedTasks() { apiFetch("/scheduled-tasks").then((r) => r.json()).then((d) => { if (Array.isArray(d)) setSchedTasks(d); }).catch(() => showToast("加载定时任务失败")); }

  async function deleteMemory(memId: number) { await apiFetch(`/memories/${memId}`, { method: "DELETE" }); setMemories((prev) => prev.filter((m) => m.id !== memId)); }

  async function handleSend() {
    const text = input.trim();
    if ((!text && !pendingFile) || streaming || !activeConvId) return;
    const displayText = text || (pendingFile ? `发送了文件: ${pendingFile.name}` : "");
    const convIdForTitle = activeConvId;
    const isFirstMsg = conversations.find(c => c.id === activeConvId)?.title === "新对话";
    const attachment = pendingFile ? { name: pendingFile.name, type: getFileType(pendingFile), preview: getFileType(pendingFile) === "image" ? await readFileAsDataURL(pendingFile) : undefined } as FileAttachment : undefined;
    setMessages((prev) => [...prev, { role: "user", content: displayText, attachment, created_at: new Date().toISOString() }]);
    setInput(""); setStreaming(true);
    const controller = new AbortController(); abortRef.current = controller;
    try {
      const formData = new FormData(); formData.append("message", text || "请处理这个文件"); formData.append("model", selectedModel);
      if (pendingFile) formData.append("file", pendingFile); setPendingFile(null);
      const res = await apiFetch(`/chat/${convIdForTitle}`, { method: "POST", body: formData, signal: controller.signal });
      if (!res.ok || !res.body) throw new Error("请求失败");
      const reader = res.body.getReader(); const decoder = new TextDecoder();
      let aiContent = ""; const toolCalls: ToolCall[] = []; let todos: { content: string; status: string }[] | undefined;
      setMessages((prev) => [...prev, { role: "assistant", content: "" }]);
      // 节流渲染：每80ms最多刷新一次UI，避免手机卡顿
      let lastRender = 0; let renderTimer: ReturnType<typeof setTimeout> | null = null;
      const RENDER_MS = 80;
      const doRender = () => {
        lastRender = Date.now(); renderTimer = null;
        const cur = aiContent; const curTools = toolCalls.length > 0 ? [...toolCalls] : undefined;
        setMessages((prev) => { const u = [...prev]; u[u.length - 1] = { role: "assistant", content: cur, toolCalls: curTools, todos }; return u; });
      };
      const scheduleRender = () => {
        const gap = Date.now() - lastRender;
        if (gap >= RENDER_MS) doRender();
        else if (!renderTimer) renderTimer = setTimeout(doRender, RENDER_MS - gap);
      };
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        for (const line of chunk.split("\n")) {
          if (!line.startsWith("data: ")) continue; const raw = line.slice(6); if (raw === "[DONE]") break;
          let event: { type: string; content?: string; tool?: string; args?: Record<string, unknown>; result_preview?: string; url?: string };
          try { event = JSON.parse(raw); } catch { aiContent += raw; scheduleRender(); continue; }
          if (event.type === "token" && event.content) aiContent += event.content;
          else if (event.type === "tool_start" && event.tool) { toolCalls.push({ tool: event.tool, args: event.args || {}, status: "running" }); if (event.tool === "write_todos" && event.args?.todos) todos = (event.args.todos as { content: string; status: string }[]).map(t => ({ ...t })); }
          else if (event.type === "tool_end" && event.tool) { const tc = toolCalls.find(t => t.tool === event.tool && t.status === "running"); if (tc) { tc.status = "done"; tc.result_preview = event.result_preview; } }
          else if (event.type === "done") { toolCalls.forEach(tc => { tc.status = "done"; }); }
          scheduleRender();
        }
      }
      if (renderTimer) clearTimeout(renderTimer);
      doRender(); // 流结束，强制最终刷新
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) setMessages((prev) => [...prev, { role: "assistant", content: "连接失败，请检查后端。" }]);
    } finally {
      abortRef.current = null; setStreaming(false);
      if (isFirstMsg && convIdForTitle && displayText.trim()) updateConversationTitle(convIdForTitle, displayText.replace(/\n/g, " ").slice(0, 30) || "新对话");
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }
  function copyToClipboard(text: string, idx: number) { navigator.clipboard.writeText(text).then(() => { setCopiedIdx(idx); setTimeout(() => setCopiedIdx(null), 2000); }); }
  function exportConversation() {
    if (!activeConvId || messages.length === 0) return;
    const conv = conversations.find(c => c.id === activeConvId); const title = conv?.title || "对话"; const now = new Date().toLocaleString("zh-CN");
    let md = `# ${title}\n\n导出时间：${now}\n\n---\n\n`;
    for (const msg of messages) { const time = msg.created_at ? new Date(msg.created_at).toLocaleString("zh-CN") : ""; const role = msg.role === "user" ? "👤 用户" : "🤖 小智"; md += `### ${role}${time ? ` (${time})` : ""}\n\n${msg.content}\n\n---\n\n`; }
    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" }); const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = `${title}.md`; a.click(); URL.revokeObjectURL(url);
  }
  async function handleRegenerate(aiIdx: number) {
    if (streaming || !activeConvId || aiIdx <= 0 || messages[aiIdx].role !== "assistant") return;
    const userMsg = messages[aiIdx - 1]; if (userMsg.role !== "user") return;
    setMessages((prev) => prev.slice(0, aiIdx));
    setInput(userMsg.content.replace(/（附文件:.*?）/, "").replace(/（附图片:.*?）/, "").trim());
    setTimeout(() => handleSend(), 50);
  }
  function handleEditStart(idx: number) { setEditingIdx(idx); setEditText(messages[idx].content); }
  async function handleEditSave(idx: number) {
    if (streaming || !activeConvId) return; const newText = editText.trim(); if (!newText) return;
    setEditingIdx(null); setMessages((prev) => prev.slice(0, idx)); setInput(newText); setTimeout(() => handleSend(), 50);
  }
  async function togglePin(convId: number, pinned: boolean) {
    await apiFetch(`/conversations/${convId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pinned: !pinned }) });
    setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, pinned: !pinned } : c)));
  }
  async function handleBranch(msgIdx: number) {
    if (!activeConvId) return;
    try { const res = await apiFetch(`/conversations/${activeConvId}/branch`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ from_message_index: msgIdx }) }); const data = await res.json(); if (res.ok) { setConversations((prev) => [{ id: data.id, title: data.title, created_at: new Date().toISOString(), pinned: false }, ...prev]); setActiveConvId(data.id); } } catch { showToast("分叉对话失败"); }
  }

  return (
    <div className="flex h-screen relative">
      <div className="bg-glow" />
      {sidebarOpen && <div className="fixed inset-0 bg-black/40 z-40 md:hidden" onClick={() => setSidebarOpen(false)} />}

      {/* 侧边栏 */}
      {sidebarOpen && (
        <aside className="fixed inset-y-0 left-0 z-50 md:relative md:z-auto flex-shrink-0 sidebar-glass flex flex-col" style={{ width: sidebarWidth }}>
          <div className="p-3 flex items-center gap-2">
            <button onClick={createConversation} className="flex-1 py-2.5 rounded-xl glass glass-hover text-sm font-medium flex items-center justify-center gap-2 transition-colors cursor-pointer"><span className="text-base">+</span> 新对话</button>
            <button onClick={() => setSidebarOpen(false)} className="w-10 h-10 rounded-xl glass glass-hover flex items-center justify-center text-sm transition-colors cursor-pointer">&larr;</button>
          </div>
          {conversations.length > 3 && (
            <div className="px-3 pb-2 space-y-1.5">
              <div className="flex gap-1">
                <button onClick={() => { setSearchMode("title"); setSearchResults([]); }} className={`text-[11px] px-2 py-0.5 rounded cursor-pointer ${searchMode === "title" ? "bg-[var(--accent-soft)] text-[var(--accent)]" : "text-gray-400 hover:text-gray-600"}`}>对话</button>
                <button onClick={() => setSearchMode("content")} className={`text-[11px] px-2 py-0.5 rounded cursor-pointer ${searchMode === "content" ? "bg-[var(--accent-soft)] text-[var(--accent)]" : "text-gray-400 hover:text-gray-600"}`}>内容</button>
              </div>
              <input type="text" placeholder={searchMode === "title" ? "搜索对话..." : "搜索消息内容..."} value={searchQuery} onChange={(e) => { setSearchQuery(e.target.value); if (searchMode === "content" && e.target.value.trim().length >= 2) { apiFetch(`/search?q=${encodeURIComponent(e.target.value.trim())}`).then((r) => r.json()).then((d) => { if (Array.isArray(d)) setSearchResults(d); }).catch(() => {}); } else { setSearchResults([]); } }} className="w-full text-sm px-3 py-2 rounded-lg glass focus:outline-none focus:ring-1 focus:ring-[var(--accent)]" />
            </div>
          )}
          <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-3">
            {(() => {
              if (searchMode === "content" && searchQuery.trim().length >= 2) {
                if (searchResults.length === 0) return <p className="text-xs text-gray-400 text-center py-4">没有匹配的消息</p>;
                return searchResults.map((r, i) => (
                  <div key={i} className="px-3 py-2 rounded-lg cursor-pointer hover:bg-[var(--surface-hover)] transition-colors" onClick={() => { setActiveConvId(r.conversation_id); setSearchQuery(""); setSearchResults([]); if (window.innerWidth < 768) setSidebarOpen(false); }}>
                    <p className="text-[11px] text-gray-400 mb-0.5">{r.conversation_title}</p>
                    <p className="text-xs text-gray-600 dark:text-gray-300 truncate">{r.content}</p>
                  </div>
                ));
              }
              const filtered = searchQuery.trim() ? conversations.filter((c) => c.title.toLowerCase().includes(searchQuery.trim().toLowerCase())) : conversations;
              if (filtered.length === 0 && searchQuery) return <p className="text-xs text-gray-400 text-center py-4">没有匹配的对话</p>;
              if (searchQuery.trim()) return filtered.map((conv) => (
                <div key={conv.id} className={`group flex items-center gap-1 px-3 py-2 rounded-lg cursor-pointer transition-colors ${conv.id === activeConvId ? "bg-[var(--accent-soft)]" : "hover:bg-[var(--surface-hover)]"}`} onClick={() => { setActiveConvId(conv.id); if (window.innerWidth < 768) setSidebarOpen(false); }}>
                  <span className="flex-1 truncate text-sm">{conv.title}</span>
                  <button onClick={(e) => { e.stopPropagation(); deleteConversation(conv.id); }} className="opacity-0 max-sm:opacity-60 group-hover:opacity-100 text-gray-400 hover:text-red-500 text-xs transition-opacity">✕</button>
                </div>
              ));
              return groupConversationsByTime(filtered).map((group) => (
                <div key={group.label}>
                  <div className="px-3 py-1.5 text-xs font-medium text-gray-400 uppercase tracking-wider">{group.label}</div>
                  {group.items.map((conv) => (
                    <div key={conv.id} className={`group flex items-center gap-1 px-3 py-2 rounded-lg cursor-pointer transition-colors ${conv.id === activeConvId ? "bg-[var(--accent-soft)]" : "hover:bg-[var(--surface-hover)]"}`} onClick={() => { setActiveConvId(conv.id); if (window.innerWidth < 768) setSidebarOpen(false); }}>
                      {conv.pinned && <span className="text-xs">📌</span>}
                      <span className="flex-1 truncate text-sm">{conv.title}</span>
                      <button onClick={(e) => { e.stopPropagation(); togglePin(conv.id, conv.pinned || false); }} className="opacity-0 max-sm:opacity-60 group-hover:opacity-100 text-gray-400 hover:text-[var(--accent)] text-xs transition-opacity" title={conv.pinned ? "取消置顶" : "置顶"}>{conv.pinned ? "↓" : "📌"}</button>
                      <button onClick={(e) => { e.stopPropagation(); deleteConversation(conv.id); }} className="opacity-0 max-sm:opacity-60 group-hover:opacity-100 text-gray-400 hover:text-red-500 text-xs transition-opacity">✕</button>
                    </div>
                  ))}
                </div>
              ));
            })()}
          </div>
          <div className="p-3 border-t border-[var(--border)] flex items-center justify-between">
            <button onClick={loadMemories} className="text-sm text-gray-500 hover:text-[var(--accent)] transition-colors cursor-pointer">记忆</button>
            <div className="flex items-center gap-1">
              <button onClick={() => { setShowSettings(true); loadSchedTasks(); }} className="w-8 h-8 flex items-center justify-center rounded-lg glass glass-hover transition-colors text-sm cursor-pointer" title="设置">⚙️</button>
              <button onClick={toggle} className="w-8 h-8 flex items-center justify-center rounded-lg glass glass-hover transition-colors text-sm cursor-pointer" title={theme === "dark" ? "切换浅色" : "切换深色"}>{theme === "dark" ? "☀️" : "🌙"}</button>
            </div>
          </div>
          {/* 侧边栏拖拽手柄（仅桌面端） */}
          <div className="hidden md:block absolute top-0 right-0 w-1 h-full cursor-col-resize hover:bg-[var(--accent)]/30 transition-colors" onMouseDown={(e) => { e.preventDefault(); const startX = e.clientX; const startWidth = sidebarWidth; const onMove = (ev: MouseEvent) => { setSidebarWidth(Math.min(400, Math.max(200, startWidth + ev.clientX - startX))); }; const onUp = () => { document.removeEventListener("mousemove", onMove); document.removeEventListener("mouseup", onUp); }; document.addEventListener("mousemove", onMove); document.addEventListener("mouseup", onUp); }} />
        </aside>
      )}

      {/* 主聊天区 */}
      <main className="flex-1 flex flex-col min-w-0">
        <header className="flex items-center gap-2 px-3 py-2 md:px-4 md:py-3">
          {!sidebarOpen && <button onClick={() => setSidebarOpen(true)} className="w-9 h-9 rounded-lg glass glass-hover flex items-center justify-center text-sm transition-colors cursor-pointer">☰</button>}
          <button onClick={createConversation} className="w-9 h-9 rounded-lg glass glass-hover flex items-center justify-center text-sm transition-colors cursor-pointer" title="新对话">+</button>
          {activeConvId && messages.length > 0 && <button onClick={exportConversation} className="w-9 h-9 rounded-lg glass glass-hover flex items-center justify-center text-sm transition-colors cursor-pointer" title="导出对话">⬇</button>}
          <div className="flex-1" />
          {models.length > 0 && <button onClick={() => { setShowSettings(true); loadSchedTasks(); }} className="sm:hidden text-[11px] text-gray-400 hover:text-[var(--accent)] transition-colors cursor-pointer truncate max-w-[80px]">{models.find((m) => m.key === selectedModel)?.name || selectedModel}</button>}
          <button onClick={toggle} className="w-9 h-9 rounded-lg glass glass-hover flex items-center justify-center text-sm transition-colors cursor-pointer" title={theme === "dark" ? "切换浅色" : "切换深色"}>{theme === "dark" ? "☀️" : "🌙"}</button>
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          <div className="max-w-3xl mx-auto px-4 py-6">
            {!activeConvId ? (
              <div className="flex flex-col items-center justify-center min-h-[60vh] space-y-8">
                <div className="avatar-glow w-20 h-20 rounded-2xl bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500 flex items-center justify-center text-white font-bold text-3xl">智</div>
                <div className="text-center space-y-3"><h2 className="text-2xl font-bold text-gray-700 dark:text-gray-100">嘿！我是小智</h2><p className="text-gray-400">有什么我能帮你的呀？随便聊聊～</p></div>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 w-full max-w-lg">
                  {suggestions.map((hint) => (
                    <button key={hint.text} onClick={() => { createConversation().then(() => { setTimeout(() => setInput(hint.text), 100); }); }} className="flex items-center gap-2 px-4 py-3 rounded-xl glass glass-hover text-sm text-left transition-colors cursor-pointer hover:scale-[1.02]"><span className="text-lg">{hint.icon}</span><span className="text-gray-600 dark:text-gray-300">{hint.text}</span></button>
                  ))}
                </div>
              </div>
            ) : messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center min-h-[60vh] space-y-6">
                <div className="avatar-glow w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500 flex items-center justify-center text-white font-bold text-2xl">智</div>
                <div className="text-center space-y-2"><p className="text-lg font-medium text-gray-700 dark:text-gray-200">有什么我能帮你的呀？</p><p className="text-sm text-gray-400">随便聊聊～</p></div>
                <div className="flex flex-wrap justify-center gap-2 max-w-md">{suggestions.map((hint) => (<button key={hint.text} onClick={() => setInput(hint.text)} className="text-sm px-4 py-2 rounded-full glass glass-hover transition-colors cursor-pointer"><span className="mr-1">{hint.icon}</span>{hint.text}</button>))}</div>
              </div>
            ) : (
              <div className="space-y-6">
                {messages.map((msg, i) => (
                  <div key={i} className={`flex gap-3 msg-enter ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                    {msg.role === "assistant" && <div className={`w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-500 flex items-center justify-center text-white font-bold text-xs shrink-0 mt-1 ${streaming && i === messages.length - 1 ? "avatar-streaming" : ""}`}>智</div>}
                    <div className="max-w-[85%] sm:max-w-[75%]">
                      <div className={`px-4 py-3 ${msg.role === "user" ? "bubble-user whitespace-pre-wrap" : "bubble-ai"}`}>
                        {msg.role === "assistant" ? (
                          <MarkdownRenderer content={msg.content} />
                        ) : editingIdx === i ? (
                          <div className="space-y-2"><textarea value={editText} onChange={(e) => setEditText(e.target.value)} className="w-full bg-transparent border border-white/20 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none min-h-[60px]" autoFocus /><div className="flex gap-2 justify-end"><button onClick={() => setEditingIdx(null)} className="text-xs px-3 py-1 rounded-lg bg-white/10 hover:bg-white/20 transition-colors cursor-pointer">取消</button><button onClick={() => handleEditSave(i)} className="text-xs px-3 py-1 rounded-lg bg-blue-500 text-white hover:bg-blue-600 transition-colors cursor-pointer">保存并发送</button></div></div>
                        ) : msg.content}
                        {msg.attachment && <div className="mt-2">{msg.attachment.type === "image" && msg.attachment.preview ? <img src={msg.attachment.preview} alt={msg.attachment.name} className="max-w-[200px] max-h-[150px] rounded-lg border border-white/20" /> : <span className="inline-flex items-center gap-1 text-xs bg-black/10 px-2 py-1 rounded">📎 {msg.attachment.name}</span>}</div>}
                        {msg.toolCalls && msg.toolCalls.length > 0 && <div className="mt-2 space-y-1">{msg.toolCalls.map((tc, j) => (<div key={j} className="flex items-center gap-1.5 text-xs text-gray-400">{tc.status === "running" ? <><span className="thinking-dots"><span /><span /><span /></span><span className="tool-running px-1.5 py-0.5 rounded">{getToolLabel(tc.tool, tc.args)}</span></> : <><span className="text-green-400">✓</span><span>{getToolLabel(tc.tool, tc.args)}</span></>}</div>))}</div>}
                        {msg.todos && msg.todos.length > 0 && <div className="mt-2 p-2.5 rounded-lg bg-black/5 dark:bg-white/5 text-xs space-y-1.5"><div className="font-medium text-gray-500 dark:text-gray-400 mb-1">📋 任务规划</div>{msg.todos.map((todo, j) => (<div key={j} className="flex items-start gap-2"><span className="mt-0.5 shrink-0">{todo.status === "completed" ? "✅" : todo.status === "in_progress" ? "⏳" : "⬜"}</span><span className={todo.status === "completed" ? "line-through text-gray-400" : "text-gray-600 dark:text-gray-300"}>{todo.content}</span></div>))}</div>}
                        {streaming && msg.role === "assistant" && i === messages.length - 1 && <span className="stream-cursor" />}
                      </div>
                      {!(streaming && i === messages.length - 1) && (
                        <div className={`flex items-center gap-1 mt-1 ml-1 transition-opacity ${mobileActionsIdx === i ? "opacity-100" : "opacity-0 max-sm:opacity-0"} hover:opacity-100 group-hover/msg:opacity-100`}>
                          <button onClick={() => setMobileActionsIdx(mobileActionsIdx === i ? null : i)} className="sm:hidden text-xs text-gray-400 px-1 py-0.5 cursor-pointer">...</button>
                          {msg.role === "assistant" && msg.content && <><button onClick={() => handleRegenerate(i)} className="text-xs text-gray-400 hover:text-[var(--accent)] px-1.5 py-0.5 rounded transition-colors cursor-pointer" title="重新生成">🔄</button><button onClick={() => speak(msg.content)} className="text-xs text-gray-400 hover:text-[var(--accent)] px-1.5 py-0.5 rounded transition-colors cursor-pointer" title={speaking ? "停止朗读" : "朗读"}>{speaking ? "⏹" : "🔊"}</button></>}
                          {msg.role === "user" && <><button onClick={() => handleEditStart(i)} className="text-xs text-gray-400 hover:text-[var(--accent)] px-1.5 py-0.5 rounded transition-colors cursor-pointer" title="编辑">✏️</button><button onClick={() => handleBranch(i)} className="text-xs text-gray-400 hover:text-[var(--accent)] px-1.5 py-0.5 rounded transition-colors cursor-pointer" title="从此处分叉新对话">分支</button></>}
                          <button onClick={() => copyToClipboard(msg.content, i)} className="text-xs text-gray-400 hover:text-[var(--accent)] px-1.5 py-0.5 rounded transition-colors cursor-pointer" title="复制">{copiedIdx === i ? "已复制" : "复制"}</button>
                          {msg.created_at && <span className="text-[11px] text-gray-400/60 ml-auto mr-1">{formatRelativeTime(msg.created_at)}</span>}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* 输入区 */}
        {activeConvId && (
          <div className="max-w-3xl mx-auto w-full px-4 pb-4 pt-2">
            {(recording || sttLoading || sttError) && (
              <div className="flex items-center gap-3 mb-2 rounded-xl px-4 py-3 glass">
                {recording ? (<><div className="flex items-center gap-1">{waveformData.map((v, i) => (<span key={i} className="w-1 bg-red-500 rounded-full transition-all duration-75" style={{ height: `${4 + (v / 255) * 24}px` }} />))}</div><span className="text-sm text-red-500 flex-1">正在录音，点击停止</span><button onClick={stopRecording} className="w-8 h-8 rounded-full bg-red-500 text-white flex items-center justify-center text-sm cursor-pointer hover:bg-red-600 transition-colors">■</button></>
                ) : sttLoading ? (<><span className="animate-spin text-amber-500">⏳</span><span className="text-sm text-amber-500 flex-1">正在识别语音...</span></>
                ) : sttError ? (<><span className="text-red-400">✕</span><span className="text-sm text-red-400 flex-1">{sttError}</span><button onClick={() => setSttError("")} className="text-xs text-gray-400 hover:text-gray-600 cursor-pointer">关闭</button></>) : null}
              </div>
            )}
            {pendingFile && <div className="flex items-center gap-2 mb-2 text-sm text-gray-500 glass rounded-lg px-3 py-1.5"><span>📎 {pendingFile.name}</span><button onClick={() => setPendingFile(null)} className="text-gray-400 hover:text-red-500 cursor-pointer">✕</button></div>}
            <div className="relative flex items-end gap-2 input-glow rounded-xl p-2">
              <input ref={fileInputRef} type="file" accept=".pdf,.docx,.xlsx,.png,.jpg,.jpeg,.gif,.webp,image/*" className="hidden" onChange={(e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                // 移动端检测：非本地文件（微信/云盘分享的 blob）通常 size=0 或 type 为空
                if (f.size === 0) { showToast("无法读取该文件，请从本地文件选择", "error"); e.target.value = ""; return; }
                setPendingFile(f); e.target.value = "";
              }} />
              <button onClick={() => fileInputRef.current?.click()} className="w-9 h-9 rounded-lg text-gray-400 hover:text-[var(--accent)] hover:bg-[var(--accent-soft)] flex items-center justify-center text-lg transition-colors shrink-0 cursor-pointer" title="上传文件">📎</button>
              <textarea value={input} onChange={(e) => { setInput(e.target.value); setShowCommands(e.target.value === "/"); }} onKeyDown={handleKeyDown} placeholder={pendingFile ? "输入对文件的提问..." : "给小智发消息...  输入 / 使用快捷指令"} rows={1} className="flex-1 resize-none rounded-lg px-3 py-2 focus:outline-none bg-transparent text-sm min-h-[36px] max-h-[120px]" />
              {showCommands && (<div className="absolute bottom-full left-0 right-0 mb-2 glass rounded-xl p-2 shadow-lg max-h-[240px] overflow-y-auto">{QUICK_COMMANDS.map((cmd) => (<button key={cmd.name} onClick={() => { setInput(cmd.prompt); setShowCommands(false); }} className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-left hover:bg-[var(--accent-soft)] transition-colors cursor-pointer"><span>{cmd.icon}</span><span className="font-medium">{cmd.name}</span><span className="text-xs text-gray-400 flex-1 truncate">{cmd.prompt.slice(0, 30)}...</span></button>))}</div>)}
              <button onClick={toggleRecording} className={`w-9 h-9 rounded-lg flex items-center justify-center text-lg transition-colors shrink-0 cursor-pointer ${recording ? "text-red-500 bg-red-500/10 animate-pulse" : sttLoading ? "text-amber-500 bg-amber-500/10" : "text-gray-400 hover:text-[var(--accent)] hover:bg-[var(--accent-soft)]"}`} title={recording ? "停止录音" : "语音输入"}>{recording ? "⏹" : sttLoading ? "⏳" : "🎤"}</button>
              {models.length > 0 && (<select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)} className="hidden sm:block text-xs border border-[var(--border)] rounded-lg px-2 py-1.5 bg-transparent shrink-0">{models.map((m) => (<option key={m.key} value={m.key}>{m.name}</option>))}</select>)}
              {streaming ? <button onClick={stopStreaming} className="px-4 py-2 bg-red-500 text-white rounded-xl text-sm font-medium hover:bg-red-600 transition-colors shrink-0 cursor-pointer">停止</button> : <button onClick={handleSend} disabled={!input.trim() && !pendingFile} className="px-4 py-2 btn-accent text-sm disabled:opacity-40 disabled:cursor-not-allowed shrink-0 cursor-pointer">发送</button>}
            </div>
          </div>
        )}
      </main>

      {/* 记忆面板 */}
      {showMemories && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4" onClick={() => setShowMemories(false)}>
          <div className="bg-white dark:bg-gray-900 rounded-xl w-full max-w-md max-h-[80vh] sm:max-h-[70vh] overflow-hidden shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-800">
              <div className="flex gap-3"><button onClick={() => setMemTab("memories")} className={`text-sm font-medium pb-0.5 cursor-pointer ${memTab === "memories" ? "text-[var(--accent)] border-b-2 border-[var(--accent)]" : "text-gray-400"}`}>记忆</button><button onClick={() => setMemTab("profile")} className={`text-sm font-medium pb-0.5 cursor-pointer ${memTab === "profile" ? "text-[var(--accent)] border-b-2 border-[var(--accent)]" : "text-gray-400"}`}>画像</button></div>
              <button onClick={() => setShowMemories(false)} className="text-gray-400 hover:text-gray-600 text-lg cursor-pointer">&times;</button>
            </div>
            <div className="p-4 overflow-y-auto max-h-[55vh] space-y-2">
              {memTab === "profile" ? (
                Object.entries(profile).length === 0 || Object.values(profile).every(v => v.length === 0) ? <p className="text-sm text-gray-400 text-center py-8">还没有画像信息，和小智多聊聊吧</p> : Object.entries(profile).map(([cat, items]) => items.length > 0 && (<div key={cat} className="space-y-1 mb-3"><div className="text-xs font-medium text-gray-400 uppercase">{cat === "profile" ? "个人信息" : cat === "preference" ? "偏好" : cat === "knowledge" ? "知识背景" : "当前任务"}</div>{items.map((item, j) => (<div key={j} className="text-sm px-3 py-1.5 rounded-lg bg-gray-50 dark:bg-gray-800/50">{item}</div>))}</div>))
              ) : memories.length === 0 ? <p className="text-sm text-gray-400 text-center py-8">还没有记忆，和小智聊聊吧</p> : memories.map((m) => (<div key={m.id} className="flex items-start gap-2 p-2 rounded-lg bg-gray-50 dark:bg-gray-800/50"><span className="text-xs px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 font-medium shrink-0">{m.category === "profile" ? "个人" : m.category === "preference" ? "偏好" : m.category === "knowledge" ? "知识" : "上下文"}</span><span className="text-sm flex-1">{m.content}</span><button onClick={() => deleteMemory(m.id)} className="text-gray-400 hover:text-red-500 text-xs shrink-0 cursor-pointer">x</button></div>))}
            </div>
          </div>
        </div>
      )}

      {/* 设置面板 */}
      {showSettings && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4" onClick={() => setShowSettings(false)}>
          <div className="bg-white dark:bg-gray-900 rounded-xl w-full max-w-md overflow-hidden shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-800"><h2 className="font-semibold text-base">设置</h2><button onClick={() => setShowSettings(false)} className="text-gray-400 hover:text-gray-600 text-lg cursor-pointer">&times;</button></div>
            <div className="p-4 space-y-4">
              <div className="space-y-2"><label className="text-sm font-medium text-gray-600 dark:text-gray-300">默认模型</label>{models.length > 0 ? <select value={selectedModel} onChange={(e) => { setSelectedModel(e.target.value); localStorage.setItem("defaultModel", e.target.value); }} className="w-full text-sm px-3 py-2 rounded-lg border border-[var(--border)] bg-transparent">{models.map((m) => (<option key={m.key} value={m.key}>{m.name}</option>))}</select> : <p className="text-sm text-gray-400">加载中...</p>}</div>
              <div className="space-y-2"><label className="text-sm font-medium text-gray-600 dark:text-gray-300">自定义指令</label><p className="text-[10px] text-gray-400">每次对话时注入到系统 prompt 中</p><textarea value={customPrompt} onChange={(e) => { setCustomPrompt(e.target.value); localStorage.setItem("customPrompt", e.target.value); }} placeholder="例：请用简洁的方式回答。" className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-transparent text-sm min-h-[80px] resize-none" /></div>
              <div className="space-y-2"><label className="text-sm font-medium text-gray-600 dark:text-gray-300">主题</label><div className="flex gap-2"><button onClick={() => { if (theme === "dark") toggle(); }} className={`flex-1 py-2 rounded-lg text-sm transition-colors cursor-pointer ${theme === "light" ? "bg-[var(--accent)] text-white" : "glass glass-hover"}`}>☀️ 浅色</button><button onClick={() => { if (theme === "light") toggle(); }} className={`flex-1 py-2 rounded-lg text-sm transition-colors cursor-pointer ${theme === "dark" ? "bg-[var(--accent)] text-white" : "glass glass-hover"}`}>🌙 深色</button></div></div>
              <div className="space-y-2"><label className="text-sm font-medium text-gray-600 dark:text-gray-300">定时任务</label><div className="space-y-2 text-sm"><input value={newTaskName} onChange={(e) => setNewTaskName(e.target.value)} placeholder="任务名称" className="w-full px-3 py-1.5 rounded-lg border border-[var(--border)] bg-transparent text-sm" /><input value={newTaskPrompt} onChange={(e) => setNewTaskPrompt(e.target.value)} placeholder="执行内容" className="w-full px-3 py-1.5 rounded-lg border border-[var(--border)] bg-transparent text-sm" /><div className="flex gap-2"><input value={newTaskCron} onChange={(e) => setNewTaskCron(e.target.value)} placeholder="Cron" className="flex-1 px-3 py-1.5 rounded-lg border border-[var(--border)] bg-transparent text-xs font-mono" /><button onClick={async () => { if (!newTaskName.trim() || !newTaskPrompt.trim()) return; await apiFetch("/scheduled-tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: newTaskName, prompt: newTaskPrompt, cron: newTaskCron }) }); setNewTaskName(""); setNewTaskPrompt(""); loadSchedTasks(); }} disabled={!newTaskName.trim() || !newTaskPrompt.trim()} className="px-3 py-1.5 rounded-lg bg-[var(--accent)] text-white text-xs disabled:opacity-40 cursor-pointer">添加</button></div><p className="text-[10px] text-gray-400">格式: 分 时 日 月 周</p></div>{schedTasks.length > 0 ? schedTasks.map((t) => (<div key={t.id} className="flex items-center gap-2 p-2 rounded-lg bg-gray-50 dark:bg-gray-800/50 text-sm"><button onClick={async () => { await apiFetch(`/scheduled-tasks/${t.id}`, { method: "PATCH" }); loadSchedTasks(); }} className={`w-3 h-3 rounded-full shrink-0 cursor-pointer ${t.enabled ? "bg-green-500" : "bg-gray-300"}`} /><span className="flex-1 truncate">{t.name}</span><span className="text-[10px] text-gray-400 font-mono">{t.cron}</span><button onClick={async () => { await apiFetch(`/scheduled-tasks/${t.id}`, { method: "DELETE" }); loadSchedTasks(); }} className="text-gray-400 hover:text-red-500 text-xs cursor-pointer">x</button></div>)) : <p className="text-xs text-gray-400 text-center py-2">暂无定时任务</p>}</div>
              <div className="pt-3 border-t border-[var(--border)] space-y-1"><div className="flex items-center gap-2"><div className="w-6 h-6 rounded-md bg-gradient-to-br from-indigo-500 to-purple-500 flex items-center justify-center text-white font-bold text-xs">智</div><span className="text-sm font-medium">小智 AI</span><span className="text-xs text-gray-400">v{backendVersion}</span></div><p className="text-xs text-gray-400">基于 DeepAgent + LangChain 的个人 AI 助手</p></div>
            </div>
          </div>
        </div>
      )}

      {/* 删除确认对话框 */}
      {pendingDeleteId && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4" onClick={() => setPendingDeleteId(null)}>
          <div className="bg-white dark:bg-gray-900 rounded-xl p-5 w-full max-w-sm shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <p className="text-sm font-medium mb-1">删除对话</p>
            <p className="text-sm text-gray-400 mb-4">确定要删除这个对话吗？此操作不可撤销。</p>
            <div className="flex gap-2 justify-end">
              <button onClick={() => setPendingDeleteId(null)} className="px-4 py-2 rounded-lg glass glass-hover text-sm cursor-pointer">取消</button>
              <button onClick={confirmDeleteConversation} className="px-4 py-2 rounded-lg bg-red-500 text-white text-sm hover:bg-red-600 cursor-pointer">删除</button>
            </div>
          </div>
        </div>
      )}

      {/* Toast 通知 */}
      <div className="fixed top-4 right-4 z-[100] space-y-2 pointer-events-none">
        {toasts.map((t) => (
          <div key={t.id} className={`pointer-events-auto px-4 py-2.5 rounded-xl text-sm font-medium shadow-lg backdrop-blur-md animate-[slideIn_0.3s_ease-out] ${
            t.type === "error" ? "bg-red-500/90 text-white"
            : t.type === "success" ? "bg-green-500/90 text-white"
            : "bg-gray-800/90 text-white"
          }`}>
            {t.message}
          </div>
        ))}
      </div>

      <style>{`@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } } @keyframes slideIn { from { opacity: 0; transform: translateX(20px); } to { opacity: 1; transform: translateX(0); } }`}</style>
    </div>
  );
}
