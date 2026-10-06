import '@quasar/extras/material-icons/material-icons.css'
import 'quasar/src/css/index.sass'

import { Notify, Dialog, Dark, type QuasarPluginOptions } from 'quasar'
import { getThemeMode, toQuasarDark } from '@/core/theme'
import i18n from '@/core/i18n'

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
