import { createApp, h, nextTick, shallowRef } from 'vue'
import { createPinia, disposePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { Quasar, QLayout, QPageContainer, Dialog, Notify, Loading } from 'quasar'
import { i18n, setLocale } from '/core/i18n/index.ts'
import { useAuthStore } from '/core/user/stores/authStore.ts'
import { useHelpStore } from '/core/user/stores/helpStore.ts'
import { contextHelpKey } from '/core/util/contextHelp.ts'
import { usePrivilegeStore } from '/core/authorize/stores/privilegeStore.ts'
import { websocket } from '/core/websocket.ts'
import 'quasar/src/css/index.sass'
import '@quasar/extras/material-icons/material-icons.css'
import '/app/style.scss'

const errors = []
window.testApp = {
  errors,
  mount(options) {
    // Keep the asynchronous mount rooted while Chromium evaluates lazy imports.
    this.pendingMount = this.mountComponent(options)
    return this.pendingMount
  },
  async mountComponent({ component, props = {}, setProps = [], containerStyle = {}, route = '/', authenticated = true, dark = false, locale = 'en' }) {
    this.unmount?.()
    errors.length = 0
    const pinia = createPinia()
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/:pathMatch(.*)*', component: { render: () => null } }],
    })
    await router.push(route)
    const auth = useAuthStore(pinia)
    if (authenticated) {
      auth.$patch({ token: 'component-test', user: { id: 1, email: 'test@example.invalid', display_name: 'Test User', language: locale } })
    }
    const privileges = usePrivilegeStore(pinia)
    await privileges.loadPrivileges()
    setLocale(locale)
    const target = (await import(/* @vite-ignore */ `/${component}`)).default
    for (const name of setProps) props[name] = new Set(props[name])
    const currentProps = shallowRef(props)
    const events = []
    const listeners = Object.fromEntries((Array.isArray(target.emits) ? target.emits : Object.keys(target.emits ?? {})).map(name => [
      `on${name[0].toUpperCase()}${name.slice(1)}`,
      (...args) => {
        events.push({ name, value: args[0], args })
        if (name.startsWith('update:')) currentProps.value = { ...currentProps.value, [name.slice(7)]: args[0] }
      },
    ]))
    const app = createApp({
      render: () => h(QLayout, {}, () => h(QPageContainer, { style: containerStyle }, () => h(target, {
        ...currentProps.value,
        ...listeners,
      }))),
    })
    app.config.errorHandler = error => errors.push(String(error.stack ?? error))
    app.use(pinia).use(router).use(i18n).use(Quasar, { plugins: { Dialog, Notify, Loading }, config: { dark } })
    app.provide(contextHelpKey, useHelpStore(pinia))
    app.mount('#app')
    Object.assign(this, {
      pinia, router, auth, privileges, events,
      async setProps(values) { currentProps.value = { ...currentProps.value, ...values }; await nextTick() },
      async navigate(value) { await router.push(value); await nextTick() },
      async dark(value) { app.config.globalProperties.$q.dark.set(value); await nextTick() },
      async patchStore(modulePath, exportName, state) {
        const module = await import(/* @vite-ignore */ `/${modulePath}`)
        module[exportName](pinia).$patch(state)
        await nextTick()
      },
      async emitSocket(name, payload) {
        for (const callback of websocket.socket?.listeners(name) ?? []) callback(payload)
        await nextTick()
      },
      unmount() { app.unmount(); disposePinia(pinia) },
    })
    await nextTick()
  },
}
