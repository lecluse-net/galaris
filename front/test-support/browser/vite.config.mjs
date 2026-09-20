import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { quasar, transformAssetUrls } from '@quasar/vite-plugin'
import { developmentWorkerRecovery } from '../../pwa/developmentWorkerRecovery.ts'

// Install an obsolete cached shell once; subsequent update requests reach Vite.
const legacyWorkerRequests = new Set()
const legacyWorkerFixture = {
  name: 'legacy-worker-fixture',
  configureServer(server) {
    server.middlewares.use((req, res, next) => {
      if (!req.url?.startsWith('/sw.js?legacy-fixture=') || legacyWorkerRequests.has(req.url)) return next()
      legacyWorkerRequests.add(req.url)
      res.setHeader('Content-Type', 'application/javascript')
      res.setHeader('Cache-Control', 'no-store')
      res.end(`
        const cacheName = 'workbox-precache-v2-' + self.registration.scope;
        self.addEventListener('install', event => event.waitUntil((async () => {
          const cache = await caches.open(cacheName);
          await cache.put('/test-support/browser/index.html', new Response('<h1>Old application</h1>', {
            headers: { 'Content-Type': 'text/html' }
          }));
          await self.skipWaiting();
        })()));
        self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
        self.addEventListener('fetch', event => {
          if (event.request.mode === 'navigate') {
            event.respondWith(caches.open(cacheName).then(cache => cache.match('/test-support/browser/index.html')));
          }
        });
      `)
    })
  },
}

// A component host only: no application bootstrap, backend proxy or production route.
export default defineConfig({
  define: { 'import.meta.env.VITE_BUILD_VERSION': JSON.stringify('test-release') },
  root: fileURLToPath(new URL('../..', import.meta.url)),
  envDir: fileURLToPath(new URL('.', import.meta.url)),
  cacheDir: '/tmp/galaris-component-vite',
  resolve: { alias: { '@': fileURLToPath(new URL('../..', import.meta.url)) } },
  plugins: [
    legacyWorkerFixture,
    developmentWorkerRecovery(),
    vue({ template: { transformAssetUrls } }),
    quasar({ sassVariables: fileURLToPath(new URL('../../quasar-variables.sass', import.meta.url)) }),
  ],
  optimizeDeps: {
    entries: ['test-support/browser/index.html'],
    noDiscovery: true,
    include: ['vue', 'pinia', 'quasar', 'quasar/dist/quasar.client.js', 'quasar/lang/en-US', 'quasar/lang/fr', 'quasar/lang/zh-CN',
      'ckeditor5', '@ckeditor/ckeditor5-vue', 'vue-router', 'vue-i18n', 'axios', 'jwt-decode', 'socket.io-client', 'marked', 'qrcode', 'echarts', 'three',
      'highlight.js/lib/common', 'highlight.js/lib/core', 'highlight.js/lib/languages/xml', 'highlight.js/lib/languages/javascript', 'highlight.js/lib/languages/css',
      'three/addons/controls/OrbitControls.js', 'three/addons/libs/meshopt_decoder.module.js',
      'three/addons/loaders/GLTFLoader.js', 'three/addons/loaders/OBJLoader.js', 'three/addons/loaders/PLYLoader.js', 'three/addons/loaders/STLLoader.js'],
  },
  server: { host: '0.0.0.0', port: 8000, strictPort: true, hmr: false },
})
