/**
 * 设备指纹管理
 *
 * 策略：localStorage 存一个 UUID 作为稳定标识，不需要复杂指纹库
 */

const DEVICE_ID_KEY = "xiaozhi_device_id";

function generateFingerprint(): string {
  const parts = [
    screen.width,
    screen.height,
    screen.colorDepth,
    Intl.DateTimeFormat().resolvedOptions().timeZone,
    navigator.language,
    navigator.platform,
    navigator.hardwareConcurrency || 0,
    navigator.maxTouchPoints || 0,
  ];
  // 简单哈希
  let hash = 0;
  const str = parts.join("|");
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash;
  }
  return Math.abs(hash).toString(36).padStart(8, "0");
}

export function getDeviceId(): string {
  if (typeof window === "undefined") return "ssr";

  const stored = localStorage.getItem(DEVICE_ID_KEY);
  if (stored) return stored;

  // 首次访问：生成新 ID
  const fingerprint = generateFingerprint();
  const random = Math.random().toString(36).substring(2, 10);
  const deviceId = `d_${fingerprint}_${random}`;

  localStorage.setItem(DEVICE_ID_KEY, deviceId);
  return deviceId;
}
