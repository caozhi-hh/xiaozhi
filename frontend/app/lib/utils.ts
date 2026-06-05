import { Conversation, Message } from "./types";

export function formatRelativeTime(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const sec = Math.floor((now.getTime() - d.getTime()) / 1000);
  if (sec < 60) return "刚刚";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}小时前`;
  const day = Math.floor(hr / 24);
  const hh = d.getHours().toString().padStart(2, "0");
  const mm = d.getMinutes().toString().padStart(2, "0");
  if (day < 2) return `昨天 ${hh}:${mm}`;
  if (day < 7) return `${day}天前`;
  return `${d.getMonth() + 1}/${d.getDate()} ${hh}:${mm}`;
}

export function getTimeGroup(dateStr: string): string {
  const d = new Date(dateStr);
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24));
  if (diffDays === 0) return "今天";
  if (diffDays === 1) return "昨天";
  if (diffDays < 7) return "最近 7 天";
  if (diffDays < 30) return "最近 30 天";
  return "更早";
}

export function groupConversationsByTime(convs: Conversation[]) {
  const pinned = convs.filter(c => c.pinned);
  const unpinned = convs.filter(c => !c.pinned);
  const groups: { label: string; items: Conversation[] }[] = [];
  if (pinned.length > 0) groups.push({ label: "置顶", items: pinned });
  const groupMap = new Map<string, Conversation[]>();
  for (const c of unpinned) {
    const label = getTimeGroup(c.created_at);
    if (!groupMap.has(label)) groupMap.set(label, []);
    groupMap.get(label)!.push(c);
  }
  const order = ["今天", "昨天", "最近 7 天", "最近 30 天", "更早"];
  for (const label of order) {
    const items = groupMap.get(label);
    if (items && items.length > 0) groups.push({ label, items });
  }
  return groups;
}

export function getToolLabel(tool: string, args: Record<string, unknown>): string {
  switch (tool) {
    case "web_search": return `搜索"${args.query || ""}"`;
    case "get_weather": return `查询${args.city || ""}天气`;
    case "translate": return "翻译中";
    case "generate_image": return "生成图片中";
    case "write_todos": return "规划任务中";
    default: return `使用${tool}`;
  }
}

export function getFileType(file: File): "image" | "pdf" | "other" {
  if (file.type.startsWith("image/")) return "image";
  if (file.type === "application/pdf" || file.name.endsWith(".pdf")) return "pdf";
  return "other";
}

export function readFileAsDataURL(file: File): Promise<string> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.readAsDataURL(file);
  });
}

export const QUICK_COMMANDS = [
  { name: "审代码", icon: "🔍", prompt: "请帮我审查以下代码，指出潜在问题、安全漏洞和改进建议：\n\n```" },
  { name: "写周报", icon: "📝", prompt: "请帮我写一份本周工作周报，我会告诉你这周做了什么，你帮我整理成专业格式" },
  { name: "翻译", icon: "🌐", prompt: "请将以下内容翻译为英文（如果是英文则翻译为中文）：\n\n" },
  { name: "总结", icon: "📋", prompt: "请帮我总结以下内容的要点，用简洁的中文列表形式：\n\n" },
  { name: "头脑风暴", icon: "💡", prompt: "我们来头脑风暴一下，主题是：" },
  { name: "解释概念", icon: "📖", prompt: "请用简单易懂的方式解释以下概念，配合比喻和例子：\n\n" },
];
