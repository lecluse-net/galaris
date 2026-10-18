import { createRouter, createWebHistory } from 'vue-router'
import { routes } from 'vue-router/auto-routes'
import { settings } from '@/core/settings'

const router = createRouter({
    history: createWebHistory(),
    routes
})

router.beforeEach(to => to.meta.devOnly && !settings.is_dev ? '/' : true)

export default router
