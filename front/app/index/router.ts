import { createRouter, createWebHistory } from 'vue-router'
import { routes } from 'vue-router/auto-routes'
import { settings } from '@/core/settings'

const router = createRouter({
    history: createWebHistory(),
    routes
})

router.beforeEach(to => to.meta.devOnly && !settings.is_dev ? '/' : true)

export async function prepareDevelopmentPluginSamples(): Promise<void> {
    if (!settings.is_dev) return
    const path = '../../plugins/sample/drawing/index.ts'
    const load = import.meta.glob<() => void>('../../plugins/sample/drawing/index.ts', { import: 'registerDrawingSample' })[path]
    if (!load) throw new Error(`Drawing sample is missing from the development mount: ${path}`)
    const registerDrawingSample = await load()
    registerDrawingSample()
}

export default router
