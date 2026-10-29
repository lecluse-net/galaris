import type { preparePortableDocumentSnapshot } from '@/core/util/facade'

export { default as DataContentEditor } from './ContentEditor.vue'

/** JSON previews render literal source, including strings containing HTML. */
export const previewSnapshot: typeof preparePortableDocumentSnapshot = async source =>
  `<pre>${source.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')}</pre>`
