<template>
    <div class="markdown-content" v-html="renderedMarkdown" @click="onMarkdownClick" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { marked, Renderer, type Tokens } from 'marked'
import {
    documentResourceHref,
    linkDocumentResourceUris,
} from '../documentResource'
import { sanitizeHtml } from '../sanitizeHtml'

const props = defineProps<{
    content: string | undefined | null
    compactFrontmatter?: boolean
}>()
const router = useRouter()

const escapeHtml = (value: string): string => value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')

const jsonTokenPattern = /("(?:\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"\s*:|"(?:\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g

const highlightJson = (content: string): string => {
    let cursor = 0
    let highlighted = ''

    for (const match of content.matchAll(jsonTokenPattern)) {
        const token = match[0]
        const index = match.index
        highlighted += escapeHtml(content.slice(cursor, index))

        let tokenClass = 'json-number'
        if (token.trimEnd().endsWith(':')) {
            tokenClass = 'json-key'
        } else if (token.startsWith('"')) {
            tokenClass = 'json-string'
        } else if (token === 'true' || token === 'false') {
            tokenClass = 'json-boolean'
        } else if (token === 'null') {
            tokenClass = 'json-null'
        }

        highlighted += `<span class="${tokenClass}">${escapeHtml(token)}</span>`
        cursor = index + token.length
    }

    return highlighted + escapeHtml(content.slice(cursor))
}

const renderer = new Renderer()
const defaultCodeRenderer = renderer.code.bind(renderer)

renderer.code = (token: Tokens.Code): string => {
    const language = token.lang?.trim().split(/\s+/)[0]?.toLowerCase()
    if (language !== 'json') return defaultCodeRenderer(token)

    try {
        const parsed = JSON.parse(token.text) as unknown
        const formatted = JSON.stringify(parsed, null, 2)
        return `<pre class="json-code"><code class="language-json">${highlightJson(formatted)}</code></pre>\n`
    } catch {
        return defaultCodeRenderer(token)
    }
}

const asJsonCodeBlock = (content: string): string | null => {
    const trimmed = content.trim()
    if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return null

    try {
        const parsed = JSON.parse(trimmed) as unknown
        return `\`\`\`json\n${JSON.stringify(parsed, null, 2)}\n\`\`\``
    } catch {
        return null
    }
}

const renderMarkdown = (content: string): string => linkDocumentResourceUris(
    sanitizeHtml(marked.parse(content, { breaks: true, renderer }) as string),
)

const frontmatterPattern = /^\uFEFF?---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/

const splitFrontmatter = (content: string): { metadata: string; markdown: string } | null => {
    const match = frontmatterPattern.exec(content)
    if (!match) return null

    return {
        metadata: (match[1] ?? '').trim(),
        markdown: content.slice(match[0].length),
    }
}

type FrontmatterRow = {
    key: string
    value: string
}

const parseFrontmatterRows = (metadata: string): FrontmatterRow[] => {
    const rows: FrontmatterRow[] = []
    let current: FrontmatterRow | null = null

    for (const line of metadata.split(/\r?\n/)) {
        const field = /^([A-Za-z_][A-Za-z0-9_-]*):[ \t]*(.*)$/.exec(line)
        if (field) {
            current = { key: field[1] ?? '', value: field[2] ?? '' }
            rows.push(current)
            continue
        }

        if (current && line.trim()) {
            const separator = current.value ? '\n' : ''
            current.value += separator + line.trim()
        }
    }

    return rows
}

const unquoteFrontmatterValue = (value: string): string => {
    const trimmed = value.trim()
    if (trimmed.length < 2) return trimmed
    const quote = trimmed[0]
    return (quote === '"' || quote === "'") && trimmed.at(-1) === quote
        ? trimmed.slice(1, -1)
        : trimmed
}

const renderFrontmatter = (metadata: string): string => {
    const rows = parseFrontmatterRows(metadata)
    if (rows.length === 0) return ''

    const body = rows.map(row => (
        '<tr>'
        + `<th scope="row">${escapeHtml(row.key)}</th>`
        + `<td>${escapeHtml(unquoteFrontmatterValue(row.value))}</td>`
        + '</tr>'
    )).join('')

    return `<table class="markdown-frontmatter"><tbody>${body}</tbody></table>`
}

const renderedMarkdown = computed(() => {
    if (!props.content) return ''

    const frontmatter = props.compactFrontmatter ? splitFrontmatter(props.content) : null
    const content = frontmatter?.markdown ?? props.content
    const prefix = frontmatter ? renderFrontmatter(frontmatter.metadata) : ''

    // Function and LLM results often contain a raw JSON dump without a code fence.
    // Detect complete objects/arrays before interpreting their contents as Markdown.
    const jsonCodeBlock = asJsonCodeBlock(content)
    if (jsonCodeBlock) {
        return prefix + renderMarkdown(jsonCodeBlock)
    }

    // Convert XML tags to Markdown headings while preserving fenced code blocks.
    let transformedContent = ''
    const parts = content.split(/(```[\s\S]*?```)/g)

    for (const part of parts) {
        if (part.startsWith('```')) {
            // Preserve fenced code blocks.
            transformedContent += part
        } else {
            // Convert opening tags to headings and remove closing tags.
            transformedContent += part
                .replace(/<\/?([a-zA-Z_][a-zA-Z0-9_-]*)>/g, (match: string, tagName: string) => {
                    if (match.startsWith('</')) {
                        // Remove closing tags.
                        return ''
                    } else {
                        // Convert opening tags to H1 headings, replacing dashes and capitalizing.
                        const formattedTagName = tagName
                            .replace(/-/g, ' ')
                            .replace(/^\w/, (char: string) => char.toUpperCase())
                        return `# ${formattedTagName}`
                    }
                })
        }
    }

    // Pretty-print fenced JSON blocks.
    const indentedMarkdown = transformedContent.replace(
        /```json\s*\n([\s\S]*?)\n```/g,
        (match: string, jsonContent: string) => {
            try {
                // Parse and indent valid JSON.
                const trimmedContent = jsonContent.trim()
                if (!trimmedContent) return match
                const parsed = JSON.parse(trimmedContent)
                const formatted = JSON.stringify(parsed, null, 2)
                return '```json\n' + formatted + '\n```'
            } catch {
                // Preserve invalid JSON verbatim.
                return match
            }
        }
    )

    return prefix + renderMarkdown(indentedMarkdown)
})

function onMarkdownClick(event: MouseEvent): void {
    if (
        event.defaultPrevented
        || event.button !== 0
        || event.ctrlKey
        || event.metaKey
        || event.shiftKey
        || event.altKey
        || !(event.target instanceof Element)
    ) return

    const link = event.target.closest<HTMLAnchorElement>('a[data-document-resource-id]')
    const documentId = link?.dataset.documentResourceId
    if (!link || !documentId || link.target === '_blank' || link.hasAttribute('download')) return

    event.preventDefault()
    void router.push(documentResourceHref(documentId))
}

</script>

<style scoped>
.markdown-content :deep(h1) {
    font-size: 1.5em;
    margin: 0.5em 0;
    font-weight: 600;
}

.markdown-content :deep(h2) {
    font-size: 1.3em;
    margin: 0.4em 0;
    font-weight: 600;
}

.markdown-content :deep(h3) {
    font-size: 1.1em;
    margin: 0.3em 0;
    font-weight: 600;
}

.markdown-content :deep(p) {
    margin: 0.5em 0;
    line-height: 1.6;
}

.markdown-content :deep(ul),
.markdown-content :deep(ol) {
    margin: 0.5em 0;
    padding-left: 1.5em;
}

.markdown-content :deep(li) {
    margin: 0.25em 0;
}

.markdown-content :deep(code) {
    background: #f5f5f5;
    padding: 0.2em 0.4em;
    border-radius: 3px;
    font-family: monospace;
    font-size: 0.9em;
}

.markdown-content :deep(pre) {
    background: #f5f5f5;
    padding: 1em;
    border-radius: 4px;
    overflow-x: auto;
    margin: 0.5em 0;
    white-space: pre;
}

.markdown-content :deep(pre code) {
    background: none;
    padding: 0;
    white-space: pre;
}

.markdown-content :deep(table.markdown-frontmatter) {
    width: 100%;
    margin: 0 0 0.85em;
    overflow: hidden;
    border: 1px solid #d8dde6;
    border-radius: 6px;
    background: #f7f8fa;
    font-size: 0.8rem;
    font-weight: 400;
    line-height: 1.35;
    border-collapse: separate;
    border-spacing: 0;
}

.markdown-content :deep(.markdown-frontmatter th),
.markdown-content :deep(.markdown-frontmatter td) {
    padding: 5px 8px;
    border: 0;
    border-bottom: 1px solid #e1e5ec;
    vertical-align: top;
    text-align: left;
}

.markdown-content :deep(.markdown-frontmatter th) {
    width: 9rem;
    color: #455164;
    background: #edf0f4;
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    font-weight: 600;
    white-space: nowrap;
}

.markdown-content :deep(.markdown-frontmatter td) {
    border-left: 1px solid #e1e5ec;
    color: #4f5b6b;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}

.markdown-content :deep(.markdown-frontmatter tr:last-child th),
.markdown-content :deep(.markdown-frontmatter tr:last-child td) {
    border-bottom: 0;
}

.markdown-content :deep(.json-code .json-key) {
    color: #005cc5;
}

.markdown-content :deep(.json-code .json-string) {
    color: #22863a;
}

.markdown-content :deep(.json-code .json-number) {
    color: #b31d28;
}

.markdown-content :deep(.json-code .json-boolean) {
    color: #6f42c1;
}

.markdown-content :deep(.json-code .json-null) {
    color: #6a737d;
    font-style: italic;
}

.markdown-content :deep(code) {
    background: #f5f5f5;
    padding: 0.2em 0.4em;
    border-radius: 3px;
    font-family: monospace;
    font-size: 0.9em;
    white-space: pre-wrap;
}

.markdown-content :deep(blockquote) {
    border-left: 4px solid #ddd;
    padding-left: 1em;
    margin: 0.5em 0;
    color: #666;
}

.markdown-content :deep(hr) {
    border: 0;
    border-top: 1px solid #e0e0e0;
    margin: 0.75em 0;
}

.markdown-content :deep(a) {
    color: #1976d2;
    text-decoration: none;
}

.markdown-content :deep(a:hover) {
    text-decoration: underline;
}

.markdown-content :deep(table) {
    border-collapse: collapse;
    margin: 0.5em 0;
    width: 100%;
}

.markdown-content :deep(th),
.markdown-content :deep(td) {
    border: 1px solid #ddd;
    padding: 1px;
    font-size: 0.92em;
    text-align: left;
}

.markdown-content :deep(th) {
    background: #f5f5f5;
    font-weight: 600;
}

.markdown-content :deep(strong) {
    font-weight: 600;
}

body.body--dark .markdown-content :deep(code),
body.body--dark .markdown-content :deep(pre),
body.body--dark .markdown-content :deep(th) {
    background: #2a2a2a;
}

body.body--dark .markdown-content :deep(pre code) {
    background: none;
}

body.body--dark .markdown-content :deep(table.markdown-frontmatter) {
    border-color: #3a3f47;
    background: #24272d;
}

body.body--dark .markdown-content :deep(.markdown-frontmatter th) {
    border-color: #3a3f47;
    color: #d5dae2;
    background: #2c3037;
}

body.body--dark .markdown-content :deep(.markdown-frontmatter td) {
    border-color: #3a3f47;
    color: #c5ccd6;
}

body.body--dark .markdown-content :deep(.json-code .json-key) {
    color: #79b8ff;
}

body.body--dark .markdown-content :deep(.json-code .json-string) {
    color: #9ecbff;
}

body.body--dark .markdown-content :deep(.json-code .json-number) {
    color: #f97583;
}

body.body--dark .markdown-content :deep(.json-code .json-boolean) {
    color: #b392f0;
}

body.body--dark .markdown-content :deep(.json-code .json-null) {
    color: #959da5;
}

body.body--dark .markdown-content :deep(blockquote) {
    border-left-color: #4a4a4a;
    color: #a0a0a0;
}

body.body--dark .markdown-content :deep(hr) {
    border-top-color: #3a3f47;
}

body.body--dark .markdown-content :deep(th),
body.body--dark .markdown-content :deep(td) {
    border-color: #4a4a4a;
}

body.body--dark .markdown-content :deep(a) {
    color: #64b5f6;
}

.markdown-content :deep(em) {
    font-style: italic;
}
</style>
