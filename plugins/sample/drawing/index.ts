import { defineAsyncComponent, watch } from 'vue'
import { registerDocumentFormat } from '@/app/document'
import { i18n, isSupportedLocale } from '@/core/i18n'
import { drawingMessages } from './messages'
import { snapshot } from './snapshot'

export function registerDrawingSample(): void {
  watch(i18n.global.locale, locale => {
    if (isSupportedLocale(locale)) i18n.global.mergeLocaleMessage(locale, drawingMessages[locale])
  }, { immediate: true })

  registerDocumentFormat({
    code: 'sample.drawing', provider: 'sample.drawing', version: 1,
    label: 'drawingSample.name', icon: 'brush', storageKind: 'file', nativeExtension: '.png',
    editor: defineAsyncComponent(() => import('./DrawingEditor.vue')),
    preview: defineAsyncComponent(() => import('./DrawingPreview.vue')),
    validateDraft: () => true,
    snapshot,
  })
}
