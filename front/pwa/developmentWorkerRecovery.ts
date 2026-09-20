import { fileURLToPath } from 'node:url'
import { build, type Plugin } from 'vite'

// Old production clients still check /sw.js, while Vite PWA uses /dev-sw.js.
// Serve the canonical worker as a classic bundle with no cached application shell.
export function developmentWorkerRecovery(): Plugin {
    const workerPath = fileURLToPath(new URL('./sw.ts', import.meta.url))
    const workerDependencies = [workerPath, fileURLToPath(new URL('./cachePolicy.ts', import.meta.url))]
    let bundle: Promise<string> | undefined

    async function bundleWorker(): Promise<string> {
        const result = await build({
            configFile: false,
            logLevel: 'error',
            define: { 'import.meta.env.VITE_APP_ENV': '"dev"', 'process.env.NODE_ENV': '"production"' },
            build: {
                write: false,
                minify: false,
                lib: { entry: workerPath, formats: ['iife'], name: 'GalarisDevelopmentWorker' },
            },
        })
        const outputs = Array.isArray(result) ? result : [result]
        for (const output of outputs) {
            if ('output' in output) {
                const chunk = output.output.find(item => item.type === 'chunk' && item.isEntry)
                if (chunk?.type === 'chunk') return chunk.code
            }
        }
        throw new Error('Development service worker bundle has no entry chunk')
    }

    return {
        name: 'galaris-development-worker-recovery',
        apply: 'serve',
        configureServer(server) {
            server.watcher.add(workerDependencies)
            server.watcher.on('change', path => {
                if (workerDependencies.includes(path)) bundle = undefined
            })
            server.middlewares.use((req, res, next) => {
                if (req.url?.split('?')[0] !== '/sw.js') return next()
                bundle ??= bundleWorker().catch(error => {
                    bundle = undefined
                    throw error
                })
                void bundle.then(code => {
                    res.setHeader('Content-Type', 'application/javascript')
                    res.setHeader('Cache-Control', 'no-store')
                    res.end(req.method === 'HEAD' ? undefined : code)
                }, next)
            })
        },
    }
}
