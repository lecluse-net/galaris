import { registerSW } from 'virtual:pwa-register'
import { settings } from '../core/settings'

// Workbox can stop observing installation events after a failed external update.
// The native controller event still reaches every tab when a replacement claims it.
if ('serviceWorker' in navigator && !settings.is_dev) {
    let controller = navigator.serviceWorker.controller
    let reloading = false
    navigator.serviceWorker.addEventListener('controllerchange', () => {
        const previous = controller
        controller = navigator.serviceWorker.controller
        if (previous && controller && previous !== controller && !reloading) {
            reloading = true
            window.location.reload()
        }
    })
}

registerSW({
    immediate: true,
    onNeedReload() {
        // Production reloads after control changes, including external updates.
        // Preserve the virtual client's default development behavior.
        if (settings.is_dev) window.location.reload()
    },
    onRegisteredSW(_url, registration) {
        if (!registration || settings.is_dev) return
        let checking = false
        let pending = false
        const checkForUpdate = async () => {
            if (document.visibilityState !== 'visible') return
            pending = true
            if (checking) return
            checking = true
            try {
                do {
                    pending = false
                    try {
                        // onLine is only a network hint: a reachable self-hosted server
                        // must still receive checks when that hint remains false.
                        // The browser serializes updates, including an ongoing installation.
                        await registration.update()
                    } catch {
                        // Preserve the working shell after a failed deployment or connection.
                    }
                } while (pending && document.visibilityState === 'visible')
            } finally {
                checking = false
            }
        }
        void checkForUpdate()
        window.setInterval(() => { void checkForUpdate() }, 60_000)
        window.addEventListener('online', () => { void checkForUpdate() })
        document.addEventListener('visibilitychange', () => { void checkForUpdate() })
    },
})
