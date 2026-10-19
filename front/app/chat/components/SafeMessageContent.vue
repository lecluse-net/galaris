<template>
  <div class="safe-message-content">
    <template v-for="(block, index) in blocks" :key="index">
      <div
        v-if="block.kind === 'markdown'"
        class="markdown-block"
        :class="{ 'markdown-block--identified': block.copyable }"
        @click="onMarkdownClick($event, block.copyable)"
      >
        <div v-if="block.copyable" class="markdown-toolbar">
          <span class="markdown-label">
            <q-icon name="description" size="15px" />
            {{ t('codeEditor.language.markdown') }}
          </span>
          <q-btn
            flat
            dense
            no-caps
            size="sm"
            icon="content_copy"
            :label="t('common.copyShort')"
            :aria-label="t('common.copy')"
            class="markdown-copy"
            @click.stop="copyMarkdown(block.text)"
          >
            <q-tooltip>{{ t('common.copy') }}</q-tooltip>
          </q-btn>
        </div>
        <div :class="{ 'markdown-rendered': block.copyable }">
          <Markdown :content="block.text" @vue:mounted="enlargeRenderedEmojis" @vue:updated="enlargeRenderedEmojis" />
        </div>
      </div>
      <HtmlPreview v-else-if="block.kind === 'html'" :content="block.text" />
      <CodeEditor
        v-else
        class="source-code"
        :model-value="block.text"
        :language="block.language"
        :label="block.label"
        readonly
        :show-error="false"
        :visible-lines="12"
        @click.stop
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, shallowRef, watch, type VNode } from 'vue'
import { copyToClipboard, useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { CodeEditor, HtmlPreview, Markdown } from '@/core/util'
import { enlargeMessageEmojis } from '../messageEmojis'

type CodeLanguage =
  | 'json'
  | 'yaml'
  | 'xml'
  | 'markdown'
  | 'text'
  | 'javascript'
  | 'typescript'
  | 'python'
  | 'sql'
  | 'html'
  | 'css'

interface MarkdownBlock {
  kind: 'markdown'
  text: string
  copyable: boolean
}

interface CodeBlock {
  kind: 'code'
  text: string
  language: CodeLanguage
  label: string
}

interface HtmlBlock {
  kind: 'html'
  text: string
}

type ContentBlock = MarkdownBlock | HtmlBlock | CodeBlock

const props = withDefaults(defineProps<{
  content: string
  markdownSource?: boolean
  streaming?: boolean
}>(), {
  markdownSource: false,
  streaming: false,
})
const $q = useQuasar()
const { t } = useI18n()

const languageAliases: Record<string, CodeLanguage> = {
  css: 'css',
  htm: 'html',
  html: 'html',
  js: 'javascript',
  javascript: 'javascript',
  json: 'json',
  jsonc: 'json',
  md: 'markdown',
  markdown: 'markdown',
  py: 'python',
  python: 'python',
  sql: 'sql',
  ts: 'typescript',
  typescript: 'typescript',
  vue: 'html',
  xml: 'xml',
  yaml: 'yaml',
  yml: 'yaml',
}

function codeBlock(text: string, requestedLanguage = ''): CodeBlock {
  const normalizedLanguage = requestedLanguage.trim().toLowerCase()
  const language = languageAliases[normalizedLanguage] ?? 'text'
  return {
    kind: 'code',
    text,
    language,
    label: normalizedLanguage && language === 'text' ? normalizedLanguage : '',
  }
}

function rawJsonBlock(content: string): CodeBlock | null {
  const trimmed = content.trim()
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return null

  try {
    const value = JSON.parse(trimmed) as unknown
    return codeBlock(JSON.stringify(value, null, 2), 'json')
  } catch {
    return null
  }
}

function rawHtmlBlock(content: string): HtmlBlock | null {
  const trimmed = content.trim()
  if (!/^<!doctype\s+html\b|^<(?:html|body|main|section|article|div|form|table|figure|img|h[1-6])\b/i.test(trimmed)) return null
  return { kind: 'html', text: trimmed }
}

function contentBlocks(content: string): ContentBlock[] {
  const json = rawJsonBlock(content)
  if (json) return [json]
  if (props.markdownSource) return [codeBlock(content, 'markdown')]
  const html = rawHtmlBlock(content)
  if (html) return [html]

  const result: ContentBlock[] = []
  const markdownLines: string[] = []
  const codeLines: string[] = []
  let fenceCharacter = ''
  let fenceLength = 0
  let fenceLanguage = ''

  const flushMarkdown = (): void => {
    const text = markdownLines.join('\n')
    if (text.trim()) result.push({ kind: 'markdown', text, copyable: false })
    markdownLines.length = 0
  }
  const flushCode = (): void => {
    const text = codeLines.join('\n')
    const normalizedLanguage = fenceLanguage.trim().toLowerCase()
    if (['markdown', 'md'].includes(normalizedLanguage)) {
      result.push({ kind: 'markdown', text, copyable: true })
    } else if (['html', 'htm'].includes(normalizedLanguage)) {
      result.push({ kind: 'html', text })
    } else {
      result.push(codeBlock(text, fenceLanguage))
    }
    codeLines.length = 0
    fenceCharacter = ''
    fenceLength = 0
    fenceLanguage = ''
  }

  for (const line of content.split('\n')) {
    if (!fenceCharacter) {
      const openingFence = /^\s{0,3}(`{3,}|~{3,})\s*([^\s`]*)?.*$/.exec(line)
      if (!openingFence) {
        markdownLines.push(line)
        continue
      }

      flushMarkdown()
      const marker = openingFence[1] ?? '```'
      fenceCharacter = marker[0] ?? '`'
      fenceLength = marker.length
      fenceLanguage = openingFence[2] ?? ''
      continue
    }

    const closingFence = new RegExp(`^\\s{0,3}${fenceCharacter}{${fenceLength},}\\s*$`)
    if (closingFence.test(line)) {
      flushCode()
    } else {
      codeLines.push(line)
    }
  }

  if (fenceCharacter) flushCode()
  flushMarkdown()
  return result
}

// Coalesce only an actively growing response. Replacements and terminal text
// bypass the timer, so interruption, restart and completion cannot lose text.
const displayedContent = shallowRef(props.content)
let renderTimer: ReturnType<typeof setTimeout> | undefined
function flushContent(): void {
  if (renderTimer !== undefined) clearTimeout(renderTimer)
  renderTimer = undefined
  displayedContent.value = props.content
}
watch([() => props.content, () => props.streaming], () => {
  if (!props.streaming || !displayedContent.value || !props.content.startsWith(displayedContent.value)) flushContent()
  else if (renderTimer === undefined) renderTimer = setTimeout(flushContent, 50)
}, { flush: 'sync' })
onBeforeUnmount(() => { if (renderTimer !== undefined) clearTimeout(renderTimer) })
const blocks = computed<ContentBlock[]>(() => contentBlocks(displayedContent.value))

function enlargeRenderedEmojis(vnode: VNode): void {
  if (vnode.el instanceof HTMLElement) enlargeMessageEmojis(vnode.el)
}

function onMarkdownClick(event: MouseEvent, identified: boolean): void {
  if (identified) event.stopPropagation()
}

async function copyMarkdown(content: string): Promise<void> {
  try {
    await copyToClipboard(content)
    $q.notify({ type: 'positive', message: t('common.copied'), timeout: 2_000, position: 'top-right' })
  } catch {
    $q.notify({ type: 'negative', message: t('common.copyError'), timeout: 2_000, position: 'top-right' })
  }
}
</script>

<style scoped>
.safe-message-content {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  overflow-wrap: anywhere;
}

.markdown-block,
.markdown-rendered,
.safe-message-content :deep(.markdown-content) {
  min-width: 0;
  max-width: 100%;
}

.safe-message-content :deep(.markdown-content a) {
  overflow-wrap: anywhere;
  word-break: break-word;
}

.safe-message-content :deep(.markdown-content table) {
  display: block;
  max-width: 100%;
  overflow-x: auto;
}

.safe-message-content :deep(.markdown-content pre) {
  max-width: 100%;
}

.safe-message-content :deep(.chat-message-emoji) {
  display: inline-block;
  margin-inline: .015em;
  font-size: 1.6em;
  line-height: 1;
  vertical-align: -.17em;
}

.safe-message-content :deep(.markdown-content img) {
  display: block;
  width: auto;
  max-width: 100%;
  height: auto;
  object-fit: contain;
  border-radius: 8px;
}

.source-code {
  margin: 8px 0;
}

.markdown-block--identified {
  margin: 8px 0;
  overflow: hidden;
  background: var(--chat-surface-raised, #fbfcfe);
  border: 1px solid var(--chat-border-strong, rgba(53, 69, 94, .14));
  border-radius: 8px;
}

.markdown-toolbar {
  display: flex;
  min-height: 31px;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 2px 5px 2px 9px;
  color: var(--chat-text-muted, #657184);
  background: var(--chat-surface-soft, #f0f3f7);
  border-bottom: 1px solid var(--chat-border, rgba(53, 69, 94, .1));
}

.markdown-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: .68rem;
  font-weight: 650;
  letter-spacing: .035em;
  text-transform: uppercase;
}

.markdown-copy {
  min-height: 25px;
  color: var(--chat-text-muted, #657184);
  font-size: .68rem;
}

.markdown-rendered {
  padding: 8px 10px;
}

.safe-message-content :deep(.markdown-content > :first-child) {
  margin-top: 0;
}

.safe-message-content :deep(.markdown-content > :last-child) {
  margin-bottom: 0;
}

</style>
