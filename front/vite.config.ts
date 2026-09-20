import fs from 'node:fs'
import { randomUUID } from 'node:crypto'
import path from 'node:path'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import VueRouter from 'vue-router/vite'
import vue from '@vitejs/plugin-vue'
import { quasar, transformAssetUrls } from '@quasar/vite-plugin'
import { VitePWA } from 'vite-plugin-pwa'
import { developmentWorkerRecovery } from './pwa/developmentWorkerRecovery'

interface RouteFolder {
    src: string
    path: string
}

function getRoutesFolders(): RouteFolder[] {
    const folders: RouteFolder[] = []

    // Check if core/pages exists (convention for root '/')
    const corePagesPath = path.resolve(import.meta.dirname, 'core/pages');
    if (fs.existsSync(corePagesPath)) {
        folders.push({ src: 'core/pages', path: '/' });
    }

    // Read and parse modules.ts manually since we can't easily import TS in vite config without compilation
    const modulesPath = path.resolve(import.meta.dirname, 'modules.ts');
    if (!fs.existsSync(modulesPath)) {
        console.warn('modules.ts not found, defaulting to basic routes');
        return folders;
    }

    const content = fs.readFileSync(modulesPath, 'utf-8');
    // Regex to match string literals in the array (single or double quotes)
    const matches = content.match(/['"]([^'"]+)['"]/g);

    if (matches) {
        const modules = matches.map(m => m.slice(1, -1)); // Remove first and last character (quotes)
        modules.forEach(modulePath => {
            // modulePath is like 'core/user' or 'app/album'
            // We need to check if it has a 'pages' directory

            // Check specific module pages
            const fullPath = path.resolve(import.meta.dirname, modulePath);
            const pagesPath = path.join(fullPath, 'pages');

            if (fs.existsSync(pagesPath)) {
                // Determine route path. 
                // If it is 'core/user', usually we might want '/user' (or maybe root if it was core?)
                // The previous logic was:
                // baseDir/moduleName/pages -> /moduleName/
                // e.g. core/user/pages -> /user/
                // app/album/pages -> /album/

                const moduleName = path.basename(modulePath);
                folders.push({
                    src: `${modulePath}/pages`,
                    path: `/${moduleName}/`
                });
            }
        });
    }

    return folders;
}

const appName = process.env.VITE_APP_NAME || process.env.APP_NAME || 'galaris'
const appEnv = process.env.APP_ENV ?? process.env.VITE_APP_ENV ?? 'prod'
const appLabel = 'Galaris'
const backendUrl = `http://${appName}-back:8000`
// A fresh production build renews every precached resource, even unchanged URLs.
const precacheRevision = randomUUID()

// https://vitejs.dev/config/
export default defineConfig({
    define: {
        'import.meta.env.VITE_APP_ENV': JSON.stringify(appEnv),
        'import.meta.env.VITE_BUILD_VERSION': JSON.stringify(process.env.GALARIS_BUILD_VERSION || 'unknown'),
    },
    build: { manifest: true },
    plugins: [
        developmentWorkerRecovery(),
        VueRouter({
            routesFolder: getRoutesFolders(),
            dts: './typed-router.d.ts',
            logs: true
        }),
        vue({
            template: { transformAssetUrls }
        }),
        quasar({
            sassVariables: fileURLToPath(new URL('./quasar-variables.sass', import.meta.url))
        }),
        VitePWA({
            registerType: 'autoUpdate',
            injectRegister: 'auto',
            strategies: 'injectManifest',
            srcDir: 'pwa',
            // Keep the public worker URL stable. Existing installations update
            // /sw.js directly and must not be stranded behind an obsolete shell.
            filename: 'sw.ts',
            includeManifestIcons: false,
            manifest: {
                id: '/',
                name: appLabel,
                short_name: appLabel,
                description: `${appLabel} — assistant personnel`,
                start_url: '/',
                scope: '/',
                display: 'standalone',
                background_color: '#fafafa',
                theme_color: '#1976d2',
                icons: [
                    {
                        src: '/pwa/icon-192.png',
                        sizes: '192x192',
                        type: 'image/png',
                        purpose: 'any'
                    },
                    {
                        src: '/pwa/icon-512.png',
                        sizes: '512x512',
                        type: 'image/png',
                        purpose: 'any'
                    },
                    {
                        src: '/pwa/icon-maskable-192.png',
                        sizes: '192x192',
                        type: 'image/png',
                        purpose: 'maskable'
                    },
                    {
                        src: '/pwa/icon-maskable-512.png',
                        sizes: '512x512',
                        type: 'image/png',
                        purpose: 'maskable'
                    }
                ]
            },
            injectManifest: {
                injectionPoint: appEnv === 'dev' ? undefined : 'self.__WB_MANIFEST',
                manifestTransforms: [async entries => ({
                    manifest: appEnv === 'dev' ? [] : entries.map(entry => ({
                        ...entry,
                        revision: `${precacheRevision}-${entry.revision ?? ''}`,
                    })),
                    warnings: [],
                })],
                globPatterns: appEnv === 'dev' ? [] : ['**/*.{js,css,html,ico,png,svg,jpg,woff,woff2}'],
                globIgnores: ['**/swagger-ui-*'],
                maximumFileSizeToCacheInBytes: 2 * 1024 * 1024,
            },
            // Keep notifications on development phones; the worker has no cache
            // or navigation handler, so Vite owns every application request.
            devOptions: {
                enabled: true,
                type: 'module',
                navigateFallbackAllowlist: [/^\/$/]
            }
        })
    ],
    resolve: {
        alias: {
            '@': fileURLToPath(new URL('.', import.meta.url))
        }
    },
    server: {
        watch: {
            usePolling: true, // Force file polling.
            interval: 100,    // Check every 100 ms.
        },
        port: 8484,
        strictPort: true,
        allowedHosts: true,
        hmr: {
            clientPort: 443,
        },
        proxy: {
            '/socket.io': {
                target: backendUrl,
                changeOrigin: true,
                ws: true,
            },
            '/ws': {
                target: backendUrl,
                changeOrigin: true,
                ws: true,
            },
            '/api': {
                target: backendUrl,
                changeOrigin: false
            },
            '/openapi.json': {
                target: backendUrl,
                changeOrigin: false
            }
        }
    }
})
