/**
 * 统一 API 请求封装 — 自动注入 X-Device-ID
 */
import { API_URL } from "./types";
import { getDeviceId } from "./device";

export function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const deviceId = getDeviceId();
  const headers = new Headers(options.headers || undefined);
  headers.set("X-Device-ID", deviceId);

  // FormData 不设 Content-Type（浏览器自动加 boundary）
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  return fetch(`${API_URL}${path}`, { ...options, headers });
}
