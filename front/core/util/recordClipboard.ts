import { ref } from 'vue'
import { copyToClipboard, useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'

export function useRecordClipboard() {
  const { t } = useI18n()
  const $q = useQuasar()
  const copyingJson = ref(false)

  async function copyIdentifier(id: string | null | undefined): Promise<void> {
    if (!id) return
    try {
      await copyToClipboard(id)
      $q.notify({ message: t('common.copied'), color: 'positive', icon: 'check_circle', timeout: 1500, position: 'top' })
    } catch {
      $q.notify({ message: t('common.copyError'), color: 'negative', icon: 'error', timeout: 3000, position: 'top' })
    }
  }

  async function copyJson(load: () => Promise<unknown>, messages: { success: string; error: string }): Promise<void> {
    if (copyingJson.value) return
    copyingJson.value = true
    try {
      await copyToClipboard(JSON.stringify(await load(), null, 2))
      $q.notify({ color: 'positive', icon: 'check_circle', message: messages.success })
    } catch (reason) {
      console.error('Failed to copy record JSON:', reason)
      $q.notify({ color: 'negative', icon: 'error', message: messages.error })
    } finally {
      copyingJson.value = false
    }
  }

  return { copyingJson, copyIdentifier, copyJson }
}
