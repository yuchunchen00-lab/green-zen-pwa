/* =====================================================================
   綠野仙蔬・素材圖庫館 — Service Worker
   ---------------------------------------------------------------------
   快取策略：
     1. 導覽請求 (HTML)   → Network-first，離線時回快取的 index.html
     2. 同源靜態資源      → Stale-while-revalidate（先給快取、背景更新）
     3. Unsplash 遠端圖片 → Cache-first + 背景更新，另存於獨立快取並限制筆數
     4. 其他跨網域請求    → 直接放行，不介入

   改版時只需調整 VERSION，舊快取會在 activate 階段自動清除。
   ===================================================================== */

const VERSION    = 'v1.0.1';
const SHELL      = `gz-shell-${VERSION}`;   // 應用殼層（HTML/CSS/JS/圖示）
const IMAGES     = `gz-images-${VERSION}`;  // 遠端圖片
const MAX_IMAGES = 60;                      // 圖片快取上限（約 60 張後汰舊）

/* App Shell：安裝時預先快取，確保首次離線也能完整開啟 */
const PRECACHE = [
  './',
  './index.html',
  './manifest.json',
  './icons/icon.svg',
  './icons/favicon.ico',
  './icons/favicon-32.png',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/maskable-192.png',
  './icons/maskable-512.png',
  './icons/apple-touch-icon.png',
];

/* ---------------------------------------------------------------------
   install：預快取殼層。個別檔案失敗不應讓整個安裝失敗，
   因此逐筆加入並忽略錯誤。
   --------------------------------------------------------------------- */
self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL);
    await Promise.all(PRECACHE.map(async url => {
      try{
        await cache.add(new Request(url, { cache:'reload' }));
      }catch(err){
        console.warn('[SW] 預快取略過:', url, err);
      }
    }));
  })());
});

/* ---------------------------------------------------------------------
   activate：清除舊版本快取，並啟用 Navigation Preload 加速導覽
   --------------------------------------------------------------------- */
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys.filter(k => k.startsWith('gz-') && k !== SHELL && k !== IMAGES)
          .map(k => caches.delete(k))
    );
    if(self.registration.navigationPreload){
      try{ await self.registration.navigationPreload.enable(); }catch{}
    }
    await self.clients.claim();
  })());
});

/* 由頁面觸發「立即更新」 */
self.addEventListener('message', event => {
  if(event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});

/* ---------------------------------------------------------------------
   工具：限制某個快取的筆數（先進先出）
   --------------------------------------------------------------------- */
async function trimCache(cacheName, maxItems){
  const cache = await caches.open(cacheName);
  const keys  = await cache.keys();
  if(keys.length <= maxItems) return;
  await Promise.all(keys.slice(0, keys.length - maxItems).map(k => cache.delete(k)));
}

/* ---------------------------------------------------------------------
   策略 1：導覽請求 — Network-first
   有網路時永遠拿最新頁面；離線時回退到快取的 index.html
   --------------------------------------------------------------------- */
async function handleNavigate(event){
  try{
    const preload = await event.preloadResponse;
    const response = preload || await fetch(event.request);
    const cache = await caches.open(SHELL);
    cache.put('./index.html', response.clone());
    return response;
  }catch{
    const cache = await caches.open(SHELL);
    return (await cache.match('./index.html')) ||
           (await cache.match('./')) ||
           new Response(
             '<!doctype html><meta charset="utf-8">' +
             '<title>離線</title>' +
             '<body style="font-family:system-ui;padding:2rem;text-align:center">' +
             '<h1>目前離線</h1><p>請連線後重新整理，即可載入素材圖庫。</p></body>',
             { headers:{ 'Content-Type':'text/html; charset=utf-8' }, status:503 }
           );
  }
}

/* ---------------------------------------------------------------------
   策略 2：同源靜態資源 — Stale-while-revalidate
   先把快取內容交出去（快），同時在背景抓新版備用（新）
   --------------------------------------------------------------------- */
async function handleStatic(request){
  const cache  = await caches.open(SHELL);
  const cached = await cache.match(request);

  const network = fetch(request).then(response => {
    if(response && response.ok) cache.put(request, response.clone());
    return response;
  }).catch(() => null);

  return cached || (await network) || Response.error();
}

/* ---------------------------------------------------------------------
   策略 3：遠端圖片 — Cache-first（圖片不常變動，優先走快取省流量）
   --------------------------------------------------------------------- */
async function handleImage(request){
  const cache  = await caches.open(IMAGES);
  const cached = await cache.match(request);
  if(cached){
    // 背景靜默更新，不阻塞畫面
    fetch(request).then(res => {
      if(res && (res.ok || res.type === 'opaque')) cache.put(request, res.clone());
    }).catch(() => {});
    return cached;
  }
  try{
    const response = await fetch(request);
    if(response && (response.ok || response.type === 'opaque')){
      await cache.put(request, response.clone());
      trimCache(IMAGES, MAX_IMAGES);
    }
    return response;
  }catch{
    // 離線且未快取 → 回傳 504，讓頁面的 onerror 顯示友善提示
    return new Response('', { status:504, statusText:'Offline' });
  }
}

/* ---------------------------------------------------------------------
   fetch 路由
   --------------------------------------------------------------------- */
self.addEventListener('fetch', event => {
  const { request } = event;
  if(request.method !== 'GET') return;

  const url = new URL(request.url);

  // 不介入 chrome-extension:// 等非 http(s) 協定
  if(!url.protocol.startsWith('http')) return;

  if(request.mode === 'navigate'){
    event.respondWith(handleNavigate(event));
    return;
  }

  if(url.origin === self.location.origin){
    event.respondWith(handleStatic(request));
    return;
  }

  if(request.destination === 'image'){
    event.respondWith(handleImage(request));
    return;
  }

  // 其餘跨網域請求交給瀏覽器自行處理
});
