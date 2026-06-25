export interface ToolCall {
  tool: string;
  args: Record<string, unknown>;
  status: "running" | "done";
  result_preview?: string;
}

export interface FileAttachment {
  name: string;
  type: "image" | "pdf" | "other";
  preview?: string;
}

export interface GeneratedFile {
  name: string;
  url: string;
  format: string;
  kept?: boolean;
}

export interface Message {
  role: "user" | "assistant";
  content: string;
  created_at?: string;
  toolCalls?: ToolCall[];
  attachment?: FileAttachment;
  files?: GeneratedFile[];
  todos?: { content: string; status: string }[];
}

export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  pinned?: boolean;
}

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";
