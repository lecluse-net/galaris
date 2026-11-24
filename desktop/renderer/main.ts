import { createApp } from 'vue'
import { Quasar, setCssVar } from 'quasar'
import { createI18n } from 'vue-i18n'
import 'quasar/src/css/index.sass'
import '@quasar/extras/material-icons/material-icons.css'
import { solaire } from '../../front/core/util/solaire'
import '../../front/core/util/solaireTheme'
import type { DesktopAPI } from '../src/contracts'
import messages from './messages.json'
import App from './App.vue'
import Tabs from './Tabs.vue'
import Screenshot from './Screenshot.vue'

declare global { interface Window { galarisDesktop: DesktopAPI } }

const wantsScreenshot = location.search === '?screenshot'
const state = await (wantsScreenshot ? window.galarisDesktop.screenState() : window.galarisDesktop.state())
document.documentElement.lang = state.locale
setCssVar('primary', solaire.blue.accent)
setCssVar('negative', solaire.red.accent)
const i18n = createI18n({ legacy: false, locale: state.locale, fallbackLocale: 'en', messages })
const component = wantsScreenshot ? Screenshot : location.search === '?tabs' ? Tabs : App
createApp(component, { initialState: state }).use(Quasar, { config: { dark: 'auto' } }).use(i18n).mount('#q-app')
