import { copyToClipboard, useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import type { ContextAction } from './contextActions'

export function useResourceCopy(): { copy: (uri: string) => Promise<void>; action: (uri: string) => ContextAction } {
  const { t } = useI18n(), $q = useQuasar()
  async function copy(uri: string): Promise<void> {
    try { await copyToClipboard(uri); $q.notify({ type: 'positive', message: t('common.copied') }) }
    catch { $q.notify({ type: 'negative', message: t('richEditor.copyError') }) }
  }
  return { copy, action: uri => ({ key: 'copy-reference', icon: 'link', label: t('richEditor.copy'), run: () => copy(uri) }) }
}
