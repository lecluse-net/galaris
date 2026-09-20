<template>
    <div
        class="code-editor-container rich-content"
        :class="{ 'code-editor--fill': fillHeight }"
    >
        <div class="editor-toolbar">
            <div class="toolbar-left">
                <q-icon name="code" size="16px" class="q-mr-xs" />
                <span class="toolbar-label">{{ languageLabel }} {{ label }}</span>
            </div>
            <q-btn
                flat
                dense
                size="sm"
                color="grey-5"
                icon="content_copy"
                :label="$t('common.copyShort')"
                class="copy-btn"
                @click="copyContent"
            >
                <q-tooltip>{{ $t('common.copy') }}</q-tooltip>
            </q-btn>
        </div>
        <div
            class="editor-wrapper"
            :class="{ 'has-error': showError && !isValid }"
            :style="wrapperStyle"
        >
            <div v-if="showLineNumbers" class="line-numbers" ref="lineNumbersRef">
                <div
                    v-for="n in lineCount"
                    :key="n"
                    class="line-number"
                >{{ n }}</div>
            </div>
            <div class="editor-surface">
                <pre
                    ref="highlightRef"
                    class="code-highlight"
                    aria-hidden="true"
                ><code v-html="highlightedContent" /></pre>
                <textarea
                    ref="textareaRef"
                    v-model="localValue"
                    class="code-editor syntax-highlighted"
                    :class="{ 'scroll-y': isRestricted }"
                    :placeholder="placeholder"
                    :aria-label="label || languageLabel"
                    spellcheck="false"
                    :readonly="readonly"
                    wrap="off"
                    @keydown="handleKeydown"
                    @input="onInput"
                    @scroll="syncScroll"
                />
            </div>
        </div>
        <div v-if="showError && !isValid" class="error-message">
            <q-icon name="error" size="16px" class="q-mr-xs" />
            {{ t('codeEditor.invalid', { language: languageLabel, error: validationError }) }}
        </div>
    </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { highlightCode } from '../codeHighlight'
import '../richCode.css'

// Supported languages.
type Language = string

interface Props {
    modelValue: string
    label?: string
    placeholder?: string
    readonly?: boolean
    showError?: boolean
    showLineNumbers?: boolean
    visibleLines?: number
    minLines?: number
    language?: Language
    fillHeight?: boolean
}

const props = withDefaults(defineProps<Props>(), {
    label: '',
    placeholder: '',
    readonly: false,
    showError: true,
    showLineNumbers: true,
    visibleLines: 10,
    minLines: 0,
    language: 'text',
    fillHeight: false,
})

const emit = defineEmits<{
    (e: 'update:modelValue', value: string): void
    (e: 'validate', isValid: boolean): void
}>()

const $q = useQuasar()
const { t } = useI18n()
const localValue = ref(props.modelValue ?? '')

const lineNumbersRef = ref<HTMLElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const highlightRef = ref<HTMLElement | null>(null)

// Language labels.
const languageLabels: Record<Language, string> = {
    json: 'JSON',
    yaml: 'YAML',
    xml: 'XML',
    markdown: 'Markdown',
    text: '',
    javascript: 'JavaScript',
    typescript: 'TypeScript',
    python: 'Python',
    sql: 'SQL',
    html: 'HTML',
    css: 'CSS',
}

const languageLabel = computed(() => props.language === 'text'
    ? t('codeEditor.language.text')
    : languageLabels[props.language] ?? props.language)

// Default placeholders by language.
const defaultPlaceholders: Record<Language, string> = {
    json: '{\n  "key": "value"\n}',
    yaml: 'key: value\nlist:\n  - item1\n  - item2',
    xml: '<?xml version="1.0"?>\n<root>\n  <item>value</item>\n</root>',
    markdown: '',
    text: '',
    javascript: '// JavaScript code\nfunction example() {\n  return true;\n}',
    typescript: '// TypeScript code\nfunction example(): boolean {\n  return true;\n}',
    python: '# Python code\ndef example():\n    return True',
    sql: '-- SQL query\nSELECT * FROM table;',
    html: '<!-- HTML -->\n<div class="example">\n  Content\n</div>',
    css: '/* CSS */\n.example {\n  color: blue;\n}',
}

const placeholder = computed(() => {
    if (props.placeholder) return props.placeholder
    if (props.language === 'markdown') return t('codeEditor.placeholder.markdown')
    if (props.language === 'text') return t('codeEditor.placeholder.text')
    return defaultPlaceholders[props.language] ?? ''
})

type SyntaxToken =
    | 'boolean'
    | 'comment'
    | 'heading'
    | 'key'
    | 'keyword'
    | 'literal'
    | 'number'
    | 'string'
    | 'tag'

const escapeHtml = (value: string): string => value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')

function renderTokens(
    content: string,
    pattern: RegExp,
    classify: (token: string) => SyntaxToken,
): string {
    let cursor = 0
    let highlighted = ''

    for (const match of content.matchAll(pattern)) {
        const token = match[0]
        const index = match.index
        highlighted += escapeHtml(content.slice(cursor, index))
        highlighted += `<span class="syntax-${classify(token)}">${escapeHtml(token)}</span>`
        cursor = index + token.length
    }

    return highlighted + escapeHtml(content.slice(cursor))
}

const jsonTokenPattern = /("(?:\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"\s*:|"(?:\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g
const markupTokenPattern = /<!--[\s\S]*?-->|<\/?[A-Za-z][^>]*?>/g
const markdownTokenPattern = /^(?:#{1,6}|>|-{3,}|\*{3,}|_{3,})[^\n]*|`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__/gm
const genericTokenPattern = /\/\*[\s\S]*?\*\/|\/\/[^\n]*|--[^\n]*|#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\b(?:true|false|null|none|undefined|select|from|where|join|insert|update|delete|create|alter|drop|and|or|not|as|async|await|break|case|catch|class|const|continue|def|do|else|except|export|extends|finally|for|from|function|if|import|in|interface|is|let|new|pass|raise|return|switch|throw|try|type|var|while|with|yield)\b|-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b/gim

function highlightSyntax(content: string, language: Language): string {
    if (language === 'text') return escapeHtml(content)
    if (!Object.hasOwn(languageLabels, language)) return highlightCode(content, language) ?? escapeHtml(content)

    if (language === 'json') {
        return renderTokens(content, jsonTokenPattern, (token) => {
            if (token.trimEnd().endsWith(':')) return 'key'
            if (token.startsWith('"')) return 'string'
            if (token === 'true' || token === 'false') return 'boolean'
            if (token === 'null') return 'literal'
            return 'number'
        })
    }

    if (language === 'xml' || language === 'html') {
        return renderTokens(content, markupTokenPattern, (token) => token.startsWith('<!--') ? 'comment' : 'tag')
    }

    if (language === 'markdown') {
        return renderTokens(content, markdownTokenPattern, (token) => token.startsWith('#') ? 'heading' : 'keyword')
    }

    return renderTokens(content, genericTokenPattern, (token) => {
        if (token.startsWith('//') || token.startsWith('/*') || token.startsWith('--') || token.startsWith('#')) return 'comment'
        if (token.startsWith('"') || token.startsWith("'") || token.startsWith('`')) return 'string'
        if (/^-?\d/.test(token)) return 'number'
        if (/^(?:true|false|null|none|undefined)$/i.test(token)) return 'literal'
        return 'keyword'
    })
}

const highlightedContent = computed(() => {
    const highlighted = highlightSyntax(localValue.value, props.language)
    return localValue.value.endsWith('\n') ? `${highlighted} ` : highlighted
})

// Synchronize with the external value.
watch(() => props.modelValue, (newValue) => {
    const normalized = newValue ?? ''
    if (normalized !== localValue.value) {
        localValue.value = normalized
        nextTick(syncScroll)
    }
})

// Language-specific validation.
const isValid = computed(() => {
    if (!props.showError) return true
    return validateContent(localValue.value).valid
})

const validationError = computed(() => {
    return validateContent(localValue.value).error || ''
})

// Content validation.
function validateContent(content: string | undefined | null): { valid: boolean; error?: string } {
    if (!content?.trim()) return { valid: true }

    switch (props.language) {
        case 'json':
            try {
                JSON.parse(content)
                return { valid: true }
            } catch (e: unknown) {
                return { valid: false, error: e instanceof Error ? e.message : 'Invalid JSON' }
            }

        case 'yaml':
            // Basic YAML validation for simple structures.
            return validateYaml(content)

        case 'xml':
            return validateXml(content)

        case 'text':
        case 'markdown':
        case 'javascript':
        case 'typescript':
        case 'python':
        case 'sql':
        case 'html':
        case 'css':
            // These languages do not use strict validation.
            return { valid: true }

        default:
            return { valid: true }
    }
}

// Basic YAML validation.
function validateYaml(content: string): { valid: boolean; error?: string } {
    const lines = content.split('\n')
    let inMultiline = false
    let multilineIndent = 0

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i]
        const trimmed = line.trim()

        // Ignore empty lines and comments.
        if (!trimmed || trimmed.startsWith('#')) continue

        // Detect multiline blocks using | or >.
        if (trimmed.endsWith('|') || trimmed.endsWith('>')) {
            inMultiline = true
            multilineIndent = line.search(/\S/)
            continue
        }

        // Detect the end of a multiline block.
        if (inMultiline) {
            const indent = line.search(/\S/)
            if (indent === -1) continue // Empty line inside a multiline block.
            if (indent <= multilineIndent && trimmed) {
                inMultiline = false
            } else {
                continue
            }
        }

        // Validate indentation.
        const indent = line.search(/\S/)
        if (indent === -1) continue

        // List lines starting with a dash.
        if (trimmed.startsWith('- ')) {
            // OK
        }
        // Key/value pair.
        else if (trimmed.includes(':')) {
            // OK
        }
        // Key without a value.
        else if (/^[\w-]+$/.test(trimmed)) {
            // Valid parent key.
        }
        else {
            return { valid: false, error: t('codeEditor.error.yamlLine', { line: i + 1 }) }
        }
    }

    return { valid: true }
}

// Basic XML validation.
function validateXml(content: string): { valid: boolean; error?: string } {
    // Remove comments and CDATA before validation.
    const cleaned = content
        .replace(/<!--[\s\S]*?-->/g, '')
        .replace(/<!\[CDATA\[[\s\S]*?\]\]>/g, '')

    // Strip an optional XML declaration.
    const hasXmlDecl = /^<\?xml[^?]*\?>/.test(cleaned)
    let xmlContent = cleaned
    if (hasXmlDecl) {
        xmlContent = cleaned.replace(/^<\?xml[^?]*\?>/, '').trim()
    }

    // Validate opening and closing tags.
    const tagStack: string[] = []
    const tagRegex = /<(\/?)([\w-]+)[^>]*?\/?>/g
    let match

    while ((match = tagRegex.exec(xmlContent)) !== null) {
        const isClosing = match[1] === '/'
        const tagName = match[2]
        const isSelfClosing = match[0].endsWith('/>')

        if (isClosing) {
            const lastTag = tagStack.pop()
            if (lastTag !== tagName) {
                return { valid: false, error: t('codeEditor.error.xmlClosing', { tag: tagName }) }
            }
        } else if (!isSelfClosing) {
            tagStack.push(tagName)
        }
    }

    if (tagStack.length > 0) {
        return { valid: false, error: t('codeEditor.error.xmlUnclosed', { tags: tagStack.join(', ') }) }
    }

    return { valid: true }
}

const lineCount = computed(() => {
    return localValue.value.split('\n').length
})

// Synchronize vertical scrolling.
const syncScroll = () => {
    if (lineNumbersRef.value && textareaRef.value) {
        lineNumbersRef.value.scrollTop = textareaRef.value.scrollTop
    }
    if (highlightRef.value && textareaRef.value) {
        highlightRef.value.scrollTop = textareaRef.value.scrollTop
        highlightRef.value.scrollLeft = textareaRef.value.scrollLeft
    }
}

// Line height in em.
const lineHeight = 1.5
// Horizontal scrollbar height.
const scrollbarHeight = '1.1em'

const isRestricted = computed(() => {
    return props.visibleLines > 0 && props.visibleLines < lineCount.value
})

// Compute an exact component height instead of relying on inconsistent textarea rows rendering.
const wrapperStyle = computed(() => {
    if (props.fillHeight) return {}

    let lines = lineCount.value
    if (isRestricted.value) {
        lines = props.visibleLines
    }
    // Keep a minimum height for short content.
    if (props.minLines > 0 && lines < props.minLines) {
        lines = props.minLines
    }

    // 32 px accounts for vertical padding (12 px top and 20 px bottom).
    return {
        height: `calc(${lines * lineHeight}em + 32px + ${scrollbarHeight})`,
        maxHeight: `calc(${lines * lineHeight}em + 32px + ${scrollbarHeight})`
    }
})

// Input handling.
const onInput = () => {
    emit('update:modelValue', localValue.value)
    emit('validate', isValid.value)
}

// Detect contexts that require automatic indentation.
function getIndentContext(line: string): { needsExtraIndent: boolean; baseIndent: string } {
    const trimmed = line.trim()
    const match = line.match(/^\s*/)
    const baseIndent = match ? match[0] : ''

    switch (props.language) {
        case 'json':
            return {
                needsExtraIndent: trimmed.endsWith('{') || trimmed.endsWith('[') || trimmed.endsWith(','),
                baseIndent
            }
        case 'yaml':
            // YAML: indent after an object key or list item.
            return {
                needsExtraIndent: trimmed.endsWith(':') || (trimmed.startsWith('-') && !trimmed.includes(':')),
                baseIndent
            }
        case 'xml':
        case 'html':
            return {
                needsExtraIndent: /<[^/][^>]*>$/.test(trimmed) && !trimmed.endsWith('/>'),
                baseIndent
            }
        case 'python':
            return {
                needsExtraIndent: /:\s*$/.test(trimmed) && !trimmed.startsWith('#'),
                baseIndent
            }
        default:
            return { needsExtraIndent: false, baseIndent }
    }
}

// Context-sensitive key handling for Tab and Enter.
const handleKeydown = (e: KeyboardEvent) => {
    if (props.readonly) return

    const target = e.target as HTMLTextAreaElement

    if (e.key === 'Tab') {
        e.preventDefault()
        const start = target.selectionStart
        const end = target.selectionEnd
        localValue.value = localValue.value.substring(0, start) + '  ' + localValue.value.substring(end)

        nextTick(() => {
            target.selectionStart = target.selectionEnd = start + 2
        })
        onInput()
    } else if (e.key === 'Enter') {
        e.preventDefault()
        const start = target.selectionStart
        const end = target.selectionEnd

        // Auto-indentation
        const beforeCursor = localValue.value.substring(0, start)
        const lines = beforeCursor.split('\n')
        const currentLine = lines[lines.length - 1]

        const { needsExtraIndent, baseIndent } = getIndentContext(currentLine)
        let indent = baseIndent

        if (needsExtraIndent) {
            indent += '  '
        }

        const textToInsert = '\n' + indent

        localValue.value = localValue.value.substring(0, start) + textToInsert + localValue.value.substring(end)

        nextTick(() => {
            target.selectionStart = target.selectionEnd = start + textToInsert.length
            syncScroll()
        })
        onInput()
    }
}

// Copy the content.
const copyContent = async () => {
    try {
        await navigator.clipboard.writeText(localValue.value)
        $q.notify({
            type: 'positive',
            message: t('common.copied'),
            timeout: 2000,
            position: 'top-right'
        })
    } catch (err) {
        $q.notify({
            type: 'negative',
            message: t('common.copyError'),
            timeout: 2000,
            position: 'top-right'
        })
    }
}
</script>

<style scoped>
.code-editor-container {
    width: 100%;
}

.code-editor-container.code-editor--fill {
    display: flex;
    flex: 1 1 auto;
    flex-direction: column;
    height: 100%;
    min-height: 0;
}

.code-editor--fill .editor-wrapper {
    flex: 1 1 auto;
    min-height: 0;
}

.code-editor--fill .code-editor {
    overflow-y: auto;
}

.editor-header {
    margin-bottom: 8px;
}

.editor-label {
    font-size: 14px;
    font-weight: 500;
    color: #aaa;
}

.editor-toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: #252525;
    border: 1px solid #3d3d3d;
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    padding: 1px 12px;
}

.toolbar-left {
    display: flex;
    align-items: center;
    color: #858585;
    font-size: 12px;
    font-weight: 500;
}

.toolbar-label {
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.copy-btn {
    font-weight: 500;
}

.editor-wrapper {
    display: flex;
    border: 1px solid #3d3d3d;
    border-bottom-left-radius: 5px;
    border-bottom-right-radius: 5px;
    background: #1e1e1e;
    transition: border-color 0.2s;
    /* wrapperStyle controls the exact height. */
}

.editor-wrapper.has-error {
    border-color: #f44336;
}

.editor-wrapper:focus-within {
    border-color: #1976d2;
}

.editor-surface {
    position: relative;
    flex: 1 1 auto;
    min-width: 0;
    height: 100%;
    overflow: hidden;
}

.line-numbers {
    background: #252525;
    border-right: 1px solid #3d3d3d;
    padding: 12px 8px 20px 8px;
    text-align: right;
    user-select: none;
    min-width: 40px;
    overflow-y: hidden;
    height: 100%;
}

.line-number {
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: 13px;
    line-height: 1.5;
    color: #858585;
}

.code-highlight,
.code-editor {
    box-sizing: border-box;
    width: 100%;
    height: 100%;
    border: none;
    padding: 12px 12px 20px 12px;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: 13px;
    line-height: 1.5;
    white-space: pre;
    word-wrap: normal;
    overflow-wrap: normal;
    tab-size: 2;
}

.code-highlight {
    position: absolute;
    inset: 0;
    z-index: 0;
    margin: 0;
    overflow: hidden;
    pointer-events: none;
    color: #d4d4d4;
}

.code-highlight code {
    font: inherit;
    white-space: inherit;
}

.code-editor {
    position: relative;
    z-index: 1;
    outline: none;
    background: transparent;
    resize: none;
    color: #d4d4d4;
    scrollbar-gutter: stable;
    margin: 0;
    display: block;
    overflow-x: auto;
    overflow-y: hidden; /* Unrestricted editors expand with the wrapper. */
}

.code-editor.syntax-highlighted {
    color: transparent;
    caret-color: #d4d4d4;
    -webkit-text-fill-color: transparent;
}

.code-editor.syntax-highlighted::selection {
    background: rgba(38, 79, 120, 0.72);
}

.code-highlight :deep(.syntax-key) { color: #9cdcfe; }
.code-highlight :deep(.syntax-string) { color: #ce9178; }
.code-highlight :deep(.syntax-number) { color: #b5cea8; }
.code-highlight :deep(.syntax-boolean),
.code-highlight :deep(.syntax-literal),
.code-highlight :deep(.syntax-keyword) { color: #569cd6; }
.code-highlight :deep(.syntax-comment) { color: #6a9955; }
.code-highlight :deep(.syntax-tag) { color: #4ec9b0; }
.code-highlight :deep(.syntax-heading) { color: #dcdcaa; }

.code-editor-container.rich-content {
    --code-keyword: var(--solaire-violet-accent);
    --code-name: var(--solaire-cyan-accent);
    --code-string: var(--solaire-green-accent);
    --code-number: var(--solaire-salmon-accent);
    --code-attribute: var(--solaire-orange-accent);
    --code-comment: #b5b5b5;
}

.code-editor.scroll-y {
    overflow-y: auto;
}

.code-editor::placeholder {
    color: #6e6e6e;
    -webkit-text-fill-color: #6e6e6e;
}

body.body--dark .code-editor::placeholder {
    color: #8f8f8f;
    -webkit-text-fill-color: #8f8f8f;
}

.error-message {
    display: flex;
    align-items: center;
    color: #f44336;
    font-size: 12px;
    margin-top: 6px;
}
</style>
