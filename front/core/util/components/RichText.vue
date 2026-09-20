<template>
  <div class="rich-content-reader">
    <div ref="root" class="rich-content ck-content" v-html="rendered" />
    <PdfPreview v-model="pdfPreview" />
  </div>
</template>
<script setup lang="ts">
import { ref, shallowRef, watch, onBeforeUnmount, nextTick, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { sanitizeRichHtml, richLinkHref, attachmentReference, type ContentProfile } from '../richText'
import { highlightDocumentCode } from '../codeHighlight'
import { hideInteractiveSource } from '../interactiveHtml'
import { createDocumentPlayer, documentPlayer, type PdfPreviewSource } from '../documentMedia'
import PdfPreview from './PdfPreview.vue'
import '../ckeditorTheme.css'
const { content, profile = 'rich-text', resolveImage } = defineProps<{
  content: string
  profile?: ContentProfile
  resolveImage?: (documentId: string, attachmentId: string) => Promise<Blob>
}>()
const rendered = ref('')
const pdfPreview = shallowRef<PdfPreviewSource | null>(null)
const root = useTemplateRef('root')
const { t } = useI18n()
let generation = 0
let urls: string[] = []
let players: Array<{ dispose: () => void }> = []
function revoke(): void {
  pdfPreview.value = null
  players.forEach(player => player.dispose()); players = []
  urls.forEach(URL.revokeObjectURL); urls = []
}
watch(() => [content, profile, resolveImage] as const, async () => {
  const current = ++generation
  revoke()
  const doc = new DOMParser().parseFromString('<body>' + sanitizeRichHtml(content, profile), 'text/html')
  hideInteractiveSource(doc.body, t('richEditor.embeddedApplication'))
  highlightDocumentCode(doc.body)
  const targets = [...doc.body.querySelectorAll('blockquote.galaris-link-card')].map(card =>
    [...card.querySelectorAll('a[href]')].map(link => documentPlayer(
      link.getAttribute('href') ?? '', link.textContent ?? '', [...card.classList],
    )).find(Boolean),
  )
  doc.body.querySelectorAll('a').forEach(link => {
    link.setAttribute('target', '_blank')
    const href = richLinkHref(link.getAttribute('href') ?? '')
    if (href) link.setAttribute('href', href)
    else link.removeAttribute('href')
  })
  const images = [...doc.body.querySelectorAll('img')]
  const references = images.map(image => attachmentReference(image.getAttribute('src') ?? ''))
  images.forEach(image => image.removeAttribute('src'))
  rendered.value = doc.body.innerHTML
  await Promise.all(images.map(async (image, index) => {
    const reference = references[index]
    if (!reference || !resolveImage) return
    try {
      const blob = await resolveImage(...reference)
      if (current !== generation) return
      const url = URL.createObjectURL(blob)
      urls.push(url)
      image.src = url
    } catch { /* The alt text remains; no unauthorized preview is retained. */ }
  }))
  if (current === generation) {
    rendered.value = doc.body.innerHTML
    await nextTick()
    if (current !== generation || profile !== 'document') return
    root.value?.querySelectorAll('blockquote.galaris-link-card').forEach((card, index) => {
      const target = targets[index]
      if (!target) return
      const player = createDocumentPlayer(card.ownerDocument, target, (documentId, attachmentId) => resolveImage?.(documentId, attachmentId), t, source => { pdfPreview.value = source })
      if (target.kind === 'youtube') card.classList.add('galaris-youtube-card')
      card.append(player.element)
      players.push(player)
    })
  }
}, { immediate: true })
onBeforeUnmount(() => { ++generation; revoke() })
</script>
