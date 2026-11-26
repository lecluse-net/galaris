<template>
  <div class="rich-content-reader" :class="{ 'rich-content-reader--document': profile === 'document' }" @contextmenu.capture="suppressDocumentContextMenu">
    <div ref="root" class="rich-content" v-html="rendered" @click.capture="openReference" />
    <ResourceReadMenu v-if="profile !== 'document'" :root="root" :content="rendered" @open="openUri" />
    <Teleport v-for="target in codeCopies" :key="target.key" :to="target.element"><CodeBlockCopyButton :source="target.source" /></Teleport>
    <Teleport v-for="target in documentLinkIcons" :key="target.key" :to="target.element"><WorkingDocumentIcon :document-id="target.documentId" title="" size="1em" readonly /></Teleport>
    <Teleport v-for="target in embeds" :key="target.key" :to="target.element"><component :is="target.display === 'card' ? DocumentCard : DocumentEmbed" :uri="target.uri" :display="target.display" :title="target.title" :agent-id="resourceAgentId" :register-actions="registerReferenceActions && target.registerActions"
      v-bind="target.display === 'embed' ? { reference: target.card, resize: resizeReference && ((size: DocumentEmbedSize) => resizeReference?.(target.index, target.uri, size)) } : {}" /></Teleport>
    <ResourceDetailDialog v-if="detail" :target="detail" @close="closeDetail" />
    <PdfPreview v-model="pdfPreview" />
  </div>
</template>
<script setup lang="ts">
import { ref, shallowRef, watch, onBeforeUnmount, nextTick, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { useDocumentNavigation } from '../documentNavigation'
import { documentNavigationHref, documentUriFromLink } from '../documentResource'
import { resolveDocumentReferenceImage, sanitizeRichHtml, richLinkHref, richLinkIcon, richLinkTarget, attachmentReference, type ContentProfile } from '../richText'
import type { ResourceEmbedTarget } from '../resourceEmbed'
import DocumentCard from './DocumentCard.vue'
import DocumentEmbed from './DocumentEmbed.vue'
import { applyReferenceAppearance, documentReferenceCards, linkIconElement, referencePlayer, referenceSizeChanges, type DocumentEmbedSize, type DocumentReferenceAction, type RegisterDocumentReferenceActions } from '../documentReference'
import { embeddedResourceCards, isLinkedImageCard, prepareDocumentCard, renderLinkedImage, resourceCardDisplay, type ResourceImageResolver } from '../resourceCards'
import { ResourceDetailDialog, type ResourceDetailTarget } from '../resourceDetail'
import { highlightDocumentCode } from '../codeHighlight'
import { hideInteractiveSource } from '../interactiveHtml'
import { createDocumentPlayer, type PdfPreviewSource } from '../documentMedia'
import PdfPreview from './PdfPreview.vue'
import CodeBlockCopyButton from './CodeBlockCopyButton.vue'
import ResourceReadMenu from './ResourceReadMenu.vue'
import WorkingDocumentIcon from './WorkingDocumentIcon.vue'
import { useDocumentLinkIcons } from '../documentLinkIcons'
import '../editorialTheme.css'
import { webLinkCardImage, prependWebLinkImage } from '../webLinkPreview'
import { renderMath } from '../mathRendering'
import { renderSvgFigures } from '../editorialSvg'
import { renderChartFigures } from '../editorialChartDisplay'
const { content, profile = 'rich-text', resolveImage, resolveResourceImage, resourceAgentId = null, registerReferenceActions, resizeReference, openDocumentInDialog = false } = defineProps<{
  content: string
  profile?: ContentProfile
  resolveImage?: (documentId: string, attachmentId: string) => Promise<Blob>
  resolveResourceImage?: ResourceImageResolver
  resourceAgentId?: number | null
  openDocumentInDialog?: boolean
  registerReferenceActions?: (card: HTMLElement, actions: readonly DocumentReferenceAction[]) => void
  resizeReference?: (index: number, uri: string, size: DocumentEmbedSize) => void
}>()
const rendered = ref('')
const navigateDocument = useDocumentNavigation()
const embeds = shallowRef<Array<ResourceEmbedTarget & { index: number; registerActions: RegisterDocumentReferenceActions }>>([]), detail = shallowRef<ResourceDetailTarget | null>(null)
let selectedDocumentReference: Element | undefined
let documentDialogLink: HTMLElement | null = null
function closeDetail(): void {
  detail.value = null
  const link = documentDialogLink
  documentDialogLink = null
  if (link) void nextTick(() => { if (!detail.value && link.isConnected) link.focus() })
}
function openReference(event: MouseEvent): void {
  if (!(event.target instanceof Element) || event.target.closest('.q-btn, input, select, textarea, [data-document-player]')) return
  const embeddedReader = event.target.closest('[data-resource-mode="embed"] > .galaris-resource-embed')
  if (embeddedReader && root.value?.contains(embeddedReader)) return
  const link = event.target.closest('a')
    ?? (profile === 'document' ? event.target.closest('blockquote.galaris-link-card')?.querySelector('a') : null)
  selectedDocumentReference?.classList.remove('galaris-reference-selected')
  selectedDocumentReference = undefined
  if (!link) return
  const uri = link.getAttribute('data-rich-reference') ?? link.getAttribute('href') ?? ''
  if (profile === 'document' && documentUriFromLink(uri, window.location.origin) && !event.ctrlKey && !event.metaKey) {
    event.preventDefault()
    selectedDocumentReference = link.closest('blockquote.galaris-link-card') ?? link
    selectedDocumentReference.classList.add('galaris-reference-selected')
    return
  }
  const target = richLinkTarget(uri, link.textContent ?? '')
  if (!(openDocumentInDialog && target?.kind === 'document') && navigateDocument(uri)) {
    event.preventDefault(); event.stopPropagation(); return
  }
  if (target) {
    event.preventDefault()
    event.stopPropagation()
    documentDialogLink = openDocumentInDialog && target.kind === 'document' && link instanceof HTMLElement ? link : null
    detail.value = target
  }
  else if (profile === 'document' && !event.target.closest('a')) {
    const href = richLinkHref(uri)
    if (href) { event.preventDefault(); window.open(href, '_blank', 'noopener,noreferrer') }
  }
}
function suppressDocumentContextMenu(event: MouseEvent): void {
  if (profile === 'document') event.stopPropagation()
}
function openUri(uri: string): void {
  const target = richLinkTarget(uri)
  if (!(openDocumentInDialog && target?.kind === 'document') && navigateDocument(uri)) return
  detail.value = target
  if (!detail.value) {
    const href = richLinkHref(uri)
    if (href) window.open(href, '_blank', 'noopener,noreferrer')
  }
}
const pdfPreview = shallowRef<PdfPreviewSource | null>(null)
const root = useTemplateRef('root')
const { targets: documentLinkIcons, decorate: decorateDocumentLink } = useDocumentLinkIcons()
watch([rendered, root], (_value, _old, onCleanup) => {
  const disposals = [...(root.value?.querySelectorAll('a') ?? [])].map(link => {
    const name = link.dataset.resourceMode === 'link' ? richLinkIcon(link.dataset.richReference ?? '') : undefined
    if (!name) return decorateDocumentLink(link)
    const icon = linkIconElement(link.ownerDocument, name)
    link.prepend(icon)
    return () => icon.remove()
  })
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
let generation = 0, renderedGeneration = -1
let urls: string[] = []
let players: Array<{ dispose: () => void }> = []
function revoke(): void {
  embeds.value = []; detail.value = null
  pdfPreview.value = null
  players.forEach(player => player.dispose()); players = []
  urls.forEach(URL.revokeObjectURL); urls = []
}
watch(() => [content, profile, resolveImage, resolveResourceImage, resourceAgentId] as const, async (values, previous, onCleanup) => {
  // An occurrence resize changes the frame, so its mounted reader keeps its own state.
  if (profile === 'document' && root.value && renderedGeneration === generation && previous
      && values.slice(1).every((value, index) => value === previous[index + 1])) {
    const sizes = referenceSizeChanges(previous[0], content)
    const cards = sizes && documentReferenceCards(root.value)
    if (sizes && cards && sizes.length === cards.length) {
      cards.forEach((card, index) => {
        if (sizes[index]) card.setAttribute('data-resource-size', sizes[index]!)
        else card.removeAttribute('data-resource-size')
      })
      return
    }
  }
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  const current = ++generation
  revoke()
  const doc = new DOMParser().parseFromString('<body>' + sanitizeRichHtml(content, profile), 'text/html')
  hideInteractiveSource(doc.body, t('richEditor.embeddedApplication'))
  const images = [...doc.body.querySelectorAll('img')]
  if (profile === 'document') renderSvgFigures(doc.body)
  const chartRendering = profile === 'document'
    ? renderChartFigures(doc.body).catch(() => { /* Keep captions if rendering fails. */ }) : undefined
  highlightDocumentCode(doc.body)
  const mathRendering = renderMath(doc.body).catch(() => { /* Keep the visible source fallback if math assets fail. */ })
  const targets = [...doc.body.querySelectorAll('blockquote.galaris-link-card')].map(card => referencePlayer(card))
  applyReferenceAppearance(doc.body)
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
  const webCards = profile === 'document' ? [...doc.body.querySelectorAll('blockquote.galaris-web-card')] : []
  const linkedImages = profile === 'document' ? [...doc.body.querySelectorAll('blockquote')].filter(isLinkedImageCard) : []
  const references = images.map(image => attachmentReference(image.getAttribute('src') ?? ''))
  images.forEach((image, index) => {
    if (references[index]) image.setAttribute('data-rich-reference', image.getAttribute('src') ?? '')
    image.removeAttribute('src')
  })
  rendered.value = doc.body.innerHTML
  await Promise.all([mathRendering, chartRendering, ...images.map(async (image, index) => {
    const reference = references[index]
    if (!reference || !resolveImage) return
    try {
      const blob = await resolveImage(...reference)
      if (current !== generation) return
      const url = URL.createObjectURL(blob)
      urls.push(url)
      image.src = url
    } catch { /* The alt text remains; no unauthorized preview is retained. */ }
  }), ...linkedImages.map(async card => {
    try {
      const url = await renderLinkedImage(card, (uri, signal, full) => resolveResourceImage?.(uri, signal, full)
        ?? resolveDocumentReferenceImage(uri, resourceAgentId, signal, full), controller.signal)
      if (url) { if (current === generation) urls.push(url); else URL.revokeObjectURL(url) }
    } catch { /* The source reference remains usable when the preview is unavailable. */ }
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
    const cards = root.value ? documentReferenceCards(root.value) : []
    embeds.value = (root.value ? embeddedResourceCards(root.value) : []).flatMap((card, key) => {
      const link = card.querySelector('a'), uri = link?.getAttribute('data-rich-reference') ?? ''
      if (!richLinkTarget(uri)) return []
      prepareDocumentCard(card)
      const element = card.ownerDocument.createElement('div'); element.className = 'galaris-resource-embed'; card.append(element)
      return [{ key, index: cards.indexOf(card), element, card, uri, title: link?.textContent ?? '', display: resourceCardDisplay(card),
        registerActions: actions => registerReferenceActions?.(card, actions) }]
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
    renderedGeneration = current
  }
}, { immediate: true })
onBeforeUnmount(() => { ++generation; revoke() })
</script>
