<template>
  <div class="rich-content-reader">
    <div ref="root" class="rich-content" v-html="rendered" @click="openReference" />
    <Teleport v-for="target in codeCopies" :key="target.key" :to="target.element"><CodeBlockCopyButton :source="target.source" /></Teleport>
    <Teleport v-for="target in embeds" :key="target.key" :to="target.element"><ResourceEmbed :uri="target.uri" :title="target.title" /></Teleport>
    <ResourceDetailDialog v-if="detail" :target="detail" @close="detail = null" />
    <PdfPreview v-model="pdfPreview" />
  </div>
</template>
<script setup lang="ts">
import { ref, shallowRef, watch, onBeforeUnmount, nextTick, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { sanitizeRichHtml, richLinkHref, richLinkTarget, attachmentReference, type ContentProfile } from '../richText'
import { ResourceEmbed, type ResourceEmbedTarget } from '../resourceEmbed'
import { ResourceDetailDialog, type ResourceDetailTarget } from '../resourceDetail'
import { highlightDocumentCode } from '../codeHighlight'
import { hideInteractiveSource } from '../interactiveHtml'
import { createDocumentPlayer, documentPlayer, type PdfPreviewSource } from '../documentMedia'
import PdfPreview from './PdfPreview.vue'
import CodeBlockCopyButton from './CodeBlockCopyButton.vue'
import '../editorialTheme.css'
const { content, profile = 'rich-text', resolveImage } = defineProps<{
  content: string
  profile?: ContentProfile
  resolveImage?: (documentId: string, attachmentId: string) => Promise<Blob>
}>()
const rendered = ref('')
const embeds = shallowRef<ResourceEmbedTarget[]>([]), detail = shallowRef<ResourceDetailTarget | null>(null)
function openReference(event: MouseEvent): void {
  const link = event.target instanceof Element ? event.target.closest('a') : null
  const target = link && richLinkTarget(link.getAttribute('data-rich-reference') ?? '', link.textContent ?? '')
  if (target) { event.preventDefault(); detail.value = target }
}
const pdfPreview = shallowRef<PdfPreviewSource | null>(null)
const root = useTemplateRef('root')
const codeCopies = shallowRef<Array<{ key: number; element: HTMLElement; source: () => string }>>([])
let codeCopyKey = 0
watch([rendered, root, () => profile], () => {
  codeCopies.value.forEach(target => target.element.remove())
  codeCopies.value = profile === 'document' ? [...(root.value?.querySelectorAll('pre > code') ?? [])].map(code => {
    const element = code.ownerDocument.createElement('span')
    element.className = 'galaris-code-actions'
    code.parentElement!.append(element)
    return { key: ++codeCopyKey, element, source: () => code.textContent ?? '' }
  }) : []
}, { flush: 'post' })
const { t } = useI18n()
let generation = 0
let urls: string[] = []
let players: Array<{ dispose: () => void }> = []
function revoke(): void {
  embeds.value = []; detail.value = null
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
    link.setAttribute('data-rich-reference', link.getAttribute('href') ?? '')
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
    embeds.value = [...(root.value?.querySelectorAll<HTMLElement>('blockquote.galaris-process-diagram, blockquote.galaris-agent-card') ?? [])].flatMap((card, key) => {
      const link = card.querySelector('a'), uri = link?.getAttribute('data-rich-reference') ?? ''
      if (!richLinkTarget(uri)) return []
      const element = card.ownerDocument.createElement('div'); element.className = 'galaris-resource-embed'; card.append(element)
      return [{ key, element, uri, title: link?.textContent ?? '' }]
    })
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
