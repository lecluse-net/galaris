import '@quasar/extras/material-icons/material-icons.css'
import 'quasar/src/css/index.sass'

import { Notify, Dialog, Dark, type QuasarPluginOptions } from 'quasar'
import { getThemeMode, toQuasarDark } from '@/core/theme'

const quasarOptions: Partial<QuasarPluginOptions> = {
    config: {
        // Apply the theme stored on this device before the first render.
        dark: toQuasarDark(getThemeMode())
    },
    plugins: {
        Notify,
        Dialog,
        Dark
    }
}

export default quasarOptions
