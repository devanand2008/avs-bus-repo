// Only public shell assets are cached. Operational records, evidence and sessions never enter CacheStorage.
const CACHE='cfc-shell-v4-avs-branding';
self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(['/brand/logo.png','/brand/icon-192.png','/brand/icon-512.png','/offline.html'])));self.skipWaiting();});
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{if(e.request.mode==='navigate')e.respondWith(fetch(e.request).catch(()=>caches.match('/offline.html')));});
