<template>
  <DocumentToolbarFrame :mode="mode" :label="t('richEditor.content')" :class="{ 'editorial-mobile-toolbar': mobile }"
    preserve-selection :document-navigation="documentNavigation" :fullscreen-exit="fullscreenExit">
    <template v-if="!mobile">
    <slot name="leading" />
    <div v-for="group in groups" :key="group.name" role="group" :aria-label="t('richEditor.groups.' + group.name)" class="editorial-toolbar-group">
      <span v-if="mode !== 'simple'" class="editorial-toolbar-title">{{ t('richEditor.groups.' + group.name) }}</span>
      <div class="editorial-toolbar-commands">
        <div v-if="mode === 'full' && group.name === 'reading' && ($slots.voice || readingHelp)" class="editorial-toolbar-row">
          <slot name="voice" />
          <EditorialCommand v-if="readingHelp" :item="readingHelp" :option-active="optionActive" @action="dispatch" />
        </div>
        <div v-for="(row, index) in group.rows" :key="index" class="editorial-toolbar-row">
          <slot v-if="mode === 'simple' && group.name === 'reading' && index === 0" name="voice" />
          <EditorialCommand v-for="item in row.filter(item => item.key !== 'help')" :key="item.key" :item="item" :option-active="optionActive" @action="dispatch" />
        </div>
      </div>
    </div>
    </template>
    <template v-else>
      <slot name="leading" />
      <EditorialCommand v-for="item in mobileItems" :key="item.key" :item="item" compact :option-active="optionActive" @action="dispatch" />
      <slot name="voice" />
      <q-btn v-if="overflowGroups.length" flat dense icon="more_horiz" :aria-label="t('richEditor.moreTools')">
        <q-tooltip>{{ t('richEditor.moreTools') }}</q-tooltip>
        <q-menu v-model="moreOpen"><div class="editorial-toolbar-overflow" @mousedown.prevent>
          <div v-for="group in overflowGroups" :key="group.name" role="group" :aria-label="t('richEditor.groups.' + group.name)">
            <div class="editorial-toolbar-title">{{ t('richEditor.groups.' + group.name) }}</div>
            <div v-for="(row, index) in group.rows" :key="index" class="editorial-toolbar-row">
              <EditorialCommand v-for="item in row" :key="item.key" :item="item" :option-active="optionActive" @action="dispatch" />
            </div>
          </div>
        </div></q-menu>
      </q-btn>
    </template>
    <slot name="trailing" />
  </DocumentToolbarFrame>
</template>
<script setup lang="ts">
import { computed, ref, useSlots } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import type { Editor } from '@tiptap/core'
import { calloutKinds } from '../tiptapContent'
import DocumentToolbarFrame from './DocumentToolbarFrame.vue'
import EditorialCommand, { type EditorialCommandItem as Item } from './EditorialCommand.vue'
import zipIcon from '../icons/bootstrap/file-zip-fill.svg?raw'
import { solaire } from '../solaire'
import { editorialIcon } from '../editorialIcons'
import { imageAlignment } from '../imageAlignment'
const { editor, revision, mode = 'full', document = false, outlineOpen = false, source = false, findOpen = false, fullWidth = false, fullscreen = false, fits = true, disabledActions = [], hiddenActions = [], documentNavigation = false, fullscreenExit = false } = defineProps<{
  editor: Editor; revision: number; mode?: 'full' | 'simple'; document?: boolean; outlineOpen?: boolean; source?: boolean; findOpen?: boolean; fullWidth?: boolean; fullscreen?: boolean; fits?: boolean; disabledActions?: readonly string[]; hiddenActions?: readonly string[]
  documentNavigation?: boolean; fullscreenExit?: boolean
}>()
const emit = defineEmits<{ action: [key: string, value?: string] }>()
const { t } = useI18n()
const $q = useQuasar()
const slots = useSlots()
const moreOpen = ref(false)
const alignments = ['left', 'center', 'right', 'justify'] as const
function dispatch(key: string, value?: string): void {
  moreOpen.value = false
  const alignment = alignments.some(alignment => alignment === key)
  emit('action', alignment ? 'alignment' : key, alignment ? key : value)
}
const mobile = computed(() => $q.screen.lt.md && mode === 'full')
const coloredIcon = (svg: string, color: string) => 'img:data:image/svg+xml,' + encodeURIComponent(svg.replaceAll('<path ', `<path fill="${color}" `))
const simpleKeys = ['undo', 'redo', 'removeFormat', 'bold', 'italic', 'underline', 'shortcuts.inlineCode', 'heading', 'bulletList', 'orderedList', 'checklist', ...alignments, 'code', 'link', 'galarisLink', 'insertTable', 'separator']
const mobileKeys = ['undo', 'redo', 'find', 'bold', 'italic', 'removeFormat', 'heading', 'callout', 'bulletList', 'orderedList', 'checklist', 'outline', ...alignments, 'galarisLink', 'insertEmoji', 'share.action', 'fullscreen', 'help']
const mobileItems = computed(() => {
  const items = groups.value.flatMap(group => group.rows.flat())
  return mobileKeys.flatMap(key => items.find(item => item.key === key) ?? [])
})
function optionActive(key: string, value: string): boolean {
  if (key === 'heading') return !(document && activeCallout.value) && (value === '0' ? editor.isActive('paragraph') : editor.isActive('heading', { level: Number(value) }))
  if (key === 'fontSize') return editor.getAttributes('textStyle').fontSize === value + 'px'
  if (key === 'fontFamily') return (editor.getAttributes('textStyle').fontFamily ?? '') === value
  if (key === 'callout') return (editor.getAttributes('blockquote').editorialClass ?? '').includes('galaris-callout-' + value) && Boolean(value)
  return false
}
const activeCallout = computed(() => {
  void revision
  return calloutKinds.find(kind => optionActive('callout', kind))
})
const groups = computed(() => {
  void revision
  const image = editor.isActive('documentImage') ? new DOMParser().parseFromString(editor.getAttributes('documentImage').html, 'text/html').body.firstElementChild as HTMLElement : null
  const button = (key: string, icon: string, active?: boolean, reading = false): Item => ({ key,
    icon: key === 'resources.documentExportBundle' ? coloredIcon(zipIcon, solaire.blue.accent)
      : editorialIcon(key === 'fullscreen' && fullscreen ? 'restore' : key, icon),
    active, disabled: disabledActions.includes(key) || !reading && (!editor.isEditable || source) })
  const menu = (key: string, icon: string, options: Array<[string, string]>, value?: string): Item => ({ ...button(key, icon), options: options.map(([value, label]) => ({ value, label })), value })
  const heading = menu('heading', 'title', [['0', t('richEditor.shortcuts.paragraph')], ...[1, 2, 3, 4, 5, 6].map(level => [String(level), t('richEditor.headingLevel', { level })] as [string, string])], editor.isActive('heading') ? t('richEditor.headingLevel', { level: editor.getAttributes('heading').level }) : t('richEditor.shortcuts.paragraph'))
  const callout = menu('callout', 'announcement', [['', t('richEditor.shortcuts.paragraph')], ...calloutKinds.map(kind => [kind, t('richEditor.callouts.' + kind)] as [string, string])])
  if (document) {
    heading.options = [
      { label: t('richEditor.shortcuts.paragraph'), value: activeCallout.value ? '' : '0', action: activeCallout.value ? 'callout' : 'heading' },
      ...heading.options!.slice(1),
      ...callout.options!.slice(1).map(option => ({ ...option, action: 'callout' })),
    ]
    if (activeCallout.value) heading.value = t('richEditor.callouts.' + activeCallout.value)
  }
  return [
    { name: 'reading' as const, rows: [[
      ...(document ? [button('outline', 'format_list_bulleted', outlineOpen, true), { ...button('layout.full', 'width_full', fullWidth, true), disabled: !fits }] : [button('source', 'code', source, true)]), button('fullscreen', 'fullscreen', fullscreen, true), ...(document && !$q.screen.lt.md ? [button('help', 'keyboard', false, true)] : []),
    ]] },
    { name: 'editing' as const, rows: [[button('undo', 'undo'), button('redo', 'redo'), { ...button('find', 'search', findOpen, true), disabled: source || disabledActions.includes('find') }, button('selectAll', 'select_all')], [button('removeFormat', 'format_clear'),
      ...(document ? [$q.screen.lt.md ? button('share.action', 'share', false, true) : button('print', 'print', false, true), button('exportPdf', 'picture_as_pdf', false, true), button('resources.documentExportBundle', 'folder_zip', false, true)] : [])]] },
    { name: 'text' as const, rows: [[
      menu('fontFamily', 'font_download', ['default', 'Arial', 'Georgia', 'Times New Roman', 'Courier New'].map(value => [value === 'default' ? '' : value, value === 'default' ? t('richEditor.defaultFont') : value]), editor.getAttributes('textStyle').fontFamily || t('richEditor.defaultFont')),
      menu('fontSize', 'format_size', ['10', '12', '14', '16', '18', '24', '32', '48'].map(value => [value, value]), String(editor.getAttributes('textStyle').fontSize ?? '').replace('px', '') || '16'),
      ...(['bold', 'italic', 'underline', 'strike'] as const).map((key, i) => button(key, ['format_bold', 'format_italic', 'format_underlined', 'strikethrough_s'][i]!, editor.isActive(key))),
    ], [
      button('equation.inline', 'functions', editor.isActive('inlineMath')),
      ...(['subscript', 'superscript', 'code'] as const).map((key, i) => button(key === 'code' ? 'shortcuts.inlineCode' : key, ['subscript', 'superscript', 'code'][i]!, editor.isActive(key))),
      button('fontColor', 'format_color_text'), button('backgroundColor', 'format_color_fill'), button('highlight', 'border_color', editor.isActive('highlight')),
      ...(document ? [button('specialCharacters', 'emoji_symbols')] : []),
    ]] },
    { name: 'paragraph' as const, rows: [[
      heading, ...(document ? [] : [callout]),
      button('bulletList', 'format_list_bulleted', editor.isActive('bulletList')), button('orderedList', 'format_list_numbered', editor.isActive('orderedList')), ...(document || mode === 'simple' ? [button('checklist', 'checklist', editor.isActive('checklist'))] : []), button('listProperties', 'format_list_numbered_rtl'),
      ...(document ? [button('quote', 'format_quote', editor.isActive('blockquote'))] : []),
    ], [
      ...alignments.map(value => button(value, 'format_align_' + value, image ? imageAlignment(image) === value : editor.isActive({ textAlign: value }) || value === 'left' && editor.isActive({ textAlign: null }))),
      button('shortcuts.outdent', 'format_indent_decrease'), button('shortcuts.indent', 'format_indent_increase'),
      ...(document || mode === 'simple' ? [button('code', 'code', editor.isActive('codeBlock'))] : []),
      button('equation.block', 'calculate', editor.isActive('blockMath')),
    ]] },
    { name: 'insert' as const, rows: [[button('link', 'link'), button('galarisLink', 'folder_open'), ...(document ? [button('resources.uploadFile', 'upload_file')] : [])],
      ...(document || mode === 'simple' ? [[button('insertTable', 'table_chart'), ...(document ? [button('insertEmoji', 'sentiment_satisfied_alt')] : []), button('separator', 'horizontal_rule')]] : [])] },
  ].map(group => {
    const rows = group.rows.map(row => row.filter(item => !hiddenActions.includes(item.key))).filter(row => row.length)
    return { ...group, rows: mode === 'full' ? rows : [rows.flat().filter(item => simpleKeys.includes(item.key))] }
  })
    .filter(group => group.rows.some(row => row.length) || group.name === 'reading' && Boolean(slots.voice))
})
const overflowGroups = computed(() => groups.value.map(group => ({ ...group,
  rows: group.rows.map(row => row.filter(item => !mobileKeys.includes(item.key))).filter(row => row.length),
})).filter(group => group.rows.length))
const readingHelp = computed(() => groups.value.find(group => group.name === 'reading')?.rows.flat().find(item => item.key === 'help'))
</script>
