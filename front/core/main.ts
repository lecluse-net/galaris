import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { Quasar } from 'quasar'
import quasarUserOptions from '../quasar-user-options'
import App from './App.vue'
import router from '@/app/index/router'
import i18n from '@/core/i18n'
import '@/app/style.scss'
import '../pwa/register'

async function initApp() {
    const app = createApp(App)

    app.use(createPinia())
    app.use(router)
    app.use(i18n)
    app.use(Quasar, quasarUserOptions)

    app.mount('#app')
}

initApp()
