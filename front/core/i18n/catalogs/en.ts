import base from '../locales/en'
import { mergeCatalogs, type Messages } from './merge'

export default mergeCatalogs(base, import.meta.glob<Messages>(
  ['../../../app/**/i18n.ts', '../../../core/**/i18n.ts', '../../../bridge/**/i18n.ts'],
  { eager: true, import: 'default', query: '?galaris-locale=en' },
))
