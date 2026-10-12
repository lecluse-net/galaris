import { Dark, useQuasar } from 'quasar'
import { watch } from 'vue'

/** Interface theme preference: follow the system, or force light/dark. */
export type ThemeMode = 'auto' | 'light' | 'dark'

export const THEME_MODES: ThemeMode[] = ['auto', 'light', 'dark']

const STORAGE_KEY = 'theme_mode'

/** Keep the web canvas on the app theme; native system bars use the system theme. */
export function useBrowserTheme(): void {
    const $q = useQuasar()
    watch(() => $q.dark.isActive, dark => {
        const background = getComputedStyle(document.body).backgroundColor
        document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
        document.documentElement.style.backgroundColor = background
    }, { immediate: true })
}

/** Read the theme preference stored on this device (defaults to 'auto'). */
export function getThemeMode(): ThemeMode {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored === 'light' || stored === 'dark' ? stored : 'auto'
}

/** Convert a theme mode to the value expected by the Quasar Dark plugin. */
export function toQuasarDark(mode: ThemeMode): boolean | 'auto' {
    return mode === 'auto' ? 'auto' : mode === 'dark'
}

/** Apply a theme mode immediately and persist it on this device. */
export function setThemeMode(mode: ThemeMode): void {
    localStorage.setItem(STORAGE_KEY, mode)
    Dark.set(toQuasarDark(mode))
}
