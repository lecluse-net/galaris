import '@quasar/extras/material-icons/material-icons.css'
import 'quasar/src/css/index.sass'

import { Notify, Dialog, Dark, useQuasar, type QuasarPluginOptions } from 'quasar'
import { onScopeDispose, watch } from 'vue'
import { getThemeMode, toQuasarDark } from '@/core/theme'
import i18n from '@/core/i18n'

/** Keep the web canvas and the browser's live theme hint on the active theme. */
export function useBrowserTheme(): void {
    const $q = useQuasar()
    const syncTheme = (): void => {
        const background = getComputedStyle(document.body).backgroundColor
        document.documentElement.style.colorScheme = $q.dark.isActive ? 'dark' : 'light'
        document.documentElement.style.backgroundColor = background
        const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
            ?? document.createElement('meta')
        themeColor.name = 'theme-color'
        themeColor.content = background
        if (!themeColor.isConnected) document.head.append(themeColor)
    }
    watch(() => $q.dark.isActive, syncTheme, { immediate: true, flush: 'post' })
    const onVisibilityChange = (): void => {
        if (!document.hidden) syncTheme()
    }
    window.addEventListener('pageshow', syncTheme)
    document.addEventListener('visibilitychange', onVisibilityChange)
    onScopeDispose(() => {
        window.removeEventListener('pageshow', syncTheme)
        document.removeEventListener('visibilitychange', onVisibilityChange)
    })
}

const quasarOptions: Partial<QuasarPluginOptions> = {
    config: {
        // Apply the theme stored on this device before the first render.
        dark: toQuasarDark(getThemeMode()),
        notify: {
            // Quasar appends default actions to local actions and preserves each timeout.
            actions: [{
                icon: 'close',
                get 'aria-label'() { return i18n.global.t('common.close') }
            }]
        }
    },
    plugins: {
        Notify,
        Dialog,
        Dark
    }
}

export default quasarOptions
