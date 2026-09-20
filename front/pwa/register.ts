import { registerSW } from 'virtual:pwa-register'
import { settings } from '../core/settings'

// The virtual client reloads all open tabs after the replacement worker activates.
// Merely injecting registerSW.js does not install that reload listener.
registerSW({
    immediate: true,
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
