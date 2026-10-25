<template>
  <div class="rich-content-reader" :class="{ 'rich-content-reader--document': profile === 'document' }" @contextmenu.capture="suppressDocumentContextMenu">
    <div ref="root" class="rich-content" v-html="rendered" @click.capture="openReference" />
    <ResourceReadMenu v-if="profile !== 'document'" :root="root" :content="rendered" @open="openUri" />
    <Teleport v-for="target in codeCopies" :key="target.key" :to="target.element"><CodeBlockCopyButton :source="target.source" /></Teleport>
    <Teleport v-for="target in documentLinkIcons" :key="target.key" :to="target.element"><WorkingDocumentIcon :document-id="target.documentId" title="" size="1em" readonly /></Teleport>
    <Teleport v-for="target in embeds" :key="target.key" :to="target.element"><ResourceEmbed :uri="target.uri" :title="target.title" /></Teleport>
    <ResourceDetailDialog v-if="detail" :target="detail" @close="detail = null" />
    <PdfPreview v-model="pdfPreview" />
  </div>
</template>
<script setup lang="ts">
import { ref, shallowRef, watch, onBeforeUnmount, nextTick, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { useDocumentNavigation } from '../documentNavigation'
import { documentNavigationHref } from '../documentResource'
import { sanitizeRichHtml, richLinkHref, richLinkTarget, attachmentReference, type ContentProfile } from '../richText'
import { ResourceEmbed, type ResourceEmbedTarget } from '../resourceEmbed'
import { embeddedResourceCards, prepareDocumentCard } from '../resourceCards'
import { ResourceDetailDialog, type ResourceDetailTarget } from '../resourceDetail'
import { highlightDocumentCode } from '../codeHighlight'
import { hideInteractiveSource } from '../interactiveHtml'
import { createDocumentPlayer, documentPlayer, type PdfPreviewSource } from '../documentMedia'
import PdfPreview from './PdfPreview.vue'
import CodeBlockCopyButton from './CodeBlockCopyButton.vue'
import ResourceReadMenu from './ResourceReadMenu.vue'
import WorkingDocumentIcon from './WorkingDocumentIcon.vue'
import { useDocumentLinkIcons } from '../documentLinkIcons'
import '../editorialTheme.css'
import { webLinkCardImage, prependWebLinkImage } from '../webLinkPreview'
const { content, profile = 'rich-text', resolveImage } = defineProps<{
  content: string
  profile?: ContentProfile
  resolveImage?: (documentId: string, attachmentId: string) => Promise<Blob>
}>()
const rendered = ref('')
const navigateDocument = useDocumentNavigation()
const embeds = shallowRef<ResourceEmbedTarget[]>([]), detail = shallowRef<ResourceDetailTarget | null>(null)
function openReference(event: MouseEvent): void {
  if (!(event.target instanceof Element) || event.target.closest('.q-btn, input, select, textarea, [data-document-player]')) return
  const link = event.target.closest('a')
    ?? (profile === 'document' ? event.target.closest('blockquote.galaris-link-card')?.querySelector('a') : null)
  if (!link) return
  const uri = link.getAttribute('data-rich-reference') ?? link.getAttribute('href') ?? ''
  if (navigateDocument(uri)) { event.preventDefault(); event.stopPropagation(); return }
  const target = richLinkTarget(uri, link.textContent ?? '')
  if (target) { event.preventDefault(); event.stopPropagation(); detail.value = target }
  else if (profile === 'document' && !event.target.closest('a')) {
    const href = richLinkHref(uri)
    if (href) { event.preventDefault(); window.open(href, '_blank', 'noopener,noreferrer') }
  }
}
function suppressDocumentContextMenu(event: MouseEvent): void {
  if (profile === 'document') { event.preventDefault(); event.stopPropagation() }
}
function openUri(uri: string): void {
  if (!navigateDocument(uri)) detail.value = richLinkTarget(uri)
}
const pdfPreview = shallowRef<PdfPreviewSource | null>(null)
const root = useTemplateRef('root')
const { targets: documentLinkIcons, decorate: decorateDocumentLink } = useDocumentLinkIcons()
watch([rendered, root], (_value, _old, onCleanup) => {
  const disposals = [...(root.value?.querySelectorAll('a') ?? [])].map(decorateDocumentLink)
  onCleanup(() => disposals.forEach(dispose => dispose()))
}, { flush: 'post' })
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
watch(() => [content, profile, resolveImage] as const, async (_value, _old, onCleanup) => {
  const controller = new AbortController()
  onCleanup(() => controller.abort())
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
    const uri = link.getAttribute('href') ?? ''
    if (/^https?:\/\//i.test(uri)) link.setAttribute('title', uri)
    const documentHref = documentNavigationHref(uri, window.location.origin)
    if (documentHref) link.removeAttribute('target')
    else link.setAttribute('target', '_blank')
    const href = documentHref ?? richLinkHref(uri)
    if (href) link.setAttribute('href', href)
    else link.removeAttribute('href')
  })
  const images = [...doc.body.querySelectorAll('img')]
  const webCards = profile === 'document' ? [...doc.body.querySelectorAll('blockquote.galaris-web-card')] : []
  const references = images.map(image => attachmentReference(image.getAttribute('src') ?? ''))
  images.forEach(image => image.removeAttribute('src'))
  rendered.value = doc.body.innerHTML
  await Promise.all([...images.map(async (image, index) => {
    const reference = references[index]
    if (!reference || !resolveImage) return
    try {
      const blob = await resolveImage(...reference)
      if (current !== generation) return
      const url = URL.createObjectURL(blob)
      urls.push(url)
      image.src = url
    } catch { /* The alt text remains; no unauthorized preview is retained. */ }
  }), ...webCards.map(async card => {
    let blob: Blob | null
    try { blob = await webLinkCardImage(card, null, controller.signal) }
    catch { return }
    if (!blob || current !== generation) return
    const url = URL.createObjectURL(blob); urls.push(url); prependWebLinkImage(card, url)
  })])
  if (current === generation) {
    rendered.value = doc.body.innerHTML
    await nextTick()
    if (current !== generation || profile !== 'document') return
    embeds.value = (root.value ? embeddedResourceCards(root.value) : []).flatMap((card, key) => {
      const link = card.querySelector('a'), uri = link?.getAttribute('data-rich-reference') ?? ''
      if (!richLinkTarget(uri)) return []
      prepareDocumentCard(card)
      const element = card.ownerDocument.createElement('div'); element.className = 'galaris-resource-embed'; card.append(element)
      return [{ key, element, uri, title: link?.textContent ?? '' }]
    })
    root.value?.querySelectorAll('blockquote.galaris-link-card').forEach((card, index) => {
      const target = targets[index]
      if (!target) return
      const player = createDocumentPlayer(card.ownerDocument, target, (documentId, attachmentId) => resolveImage?.(documentId, attachmentId), t, source => { pdfPreview.value = source })
      player.element.dataset.documentPlayer = ''
      if (target.kind === 'youtube') card.classList.add('galaris-youtube-card')
      card.append(player.element)
      players.push(player)
    })
  }
}, { immediate: true })
onBeforeUnmount(() => { ++generation; revoke() })
</script>
