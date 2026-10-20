import type { LocaleMessageValue, VueMessageType } from 'vue-i18n'
import { deepMergeMessages } from '../merge'

export type Messages = Record<string, LocaleMessageValue<VueMessageType>>

export function mergeCatalogs(base: Messages, modules: Record<string, Messages>): Messages {
  const messages = deepMergeMessages({}, base) as Messages
  for (const key of Object.keys(modules).sort()) deepMergeMessages(messages, modules[key]!)
  return messages
}
