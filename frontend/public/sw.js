// Service Worker for 小智 AI PWA — 最简版本，只注册不做缓存
// PWA 需要注册 SW 才能安装到桌面，但我们不做请求拦截，避免影响 API 调用

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', () => {
  self.clients.claim();
});

// 不拦截任何 fetch 请求，全部由浏览器正常处理
