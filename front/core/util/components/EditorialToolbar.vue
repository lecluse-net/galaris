<template>
  <template v-if="menu">
    <EditorialCommand v-for="item in contextPrimary" :key="item.key" menu :item="item" :option-active="optionActive" @action="dispatch" />
    <q-separator />
    <q-item v-for="group in contextGroups" :key="group.name" clickable role="menuitem" aria-haspopup="menu" :aria-label="t('richEditor.groups.' + group.name)">
      <q-item-section>{{ t('richEditor.groups.' + group.name) }}</q-item-section>
      <q-item-section side><q-icon name="chevron_right" /></q-item-section>
      <ContextSubmenu max-height="70vh" max-width="calc(100vw - 16px)">
        <q-list dense role="menu" :aria-label="t('richEditor.groups.' + group.name)" @mousedown.prevent>
          <EditorialCommand v-for="item in group.items" :key="item.key" menu :item="item" :option-active="optionActive" @action="dispatch" />
        </q-list>
      </ContextSubmenu>
    </q-item>
  </template>
  <div v-else class="editorial-toolbar" :class="{ 'editorial-toolbar-single-row': singleRow }" role="toolbar" :aria-label="t('richEditor.content')" @mousedown.prevent @keydown="navigateToolbar">
    <template v-if="!mobile">
    <div v-for="group in groups" :key="group.name" role="group" :aria-label="t('richEditor.groups.' + group.name)" class="editorial-toolbar-group">
      <span v-if="!singleRow" class="editorial-toolbar-title">{{ t('richEditor.groups.' + group.name) }}</span>
      <div class="editorial-toolbar-commands">
        <div v-if="group.name === 'reading' && $slots.voice" class="editorial-toolbar-row"><slot name="voice" /></div>
        <div v-for="(row, index) in group.rows" :key="index" class="editorial-toolbar-row">
          <EditorialCommand v-for="item in row" :key="item.key" :item="item" :option-active="optionActive" @action="dispatch" />
        </div>
      </div>
    </div>
    </template>
    <div v-else class="editorial-mobile-toolbar">
      <EditorialCommand v-for="item in mobileItems" :key="item.key" :item="item" compact :option-active="optionActive" @action="dispatch" />
      <slot v-if="!hiddenGroups.includes('reading')" name="voice" />
      <q-btn flat dense icon="more_horiz" :aria-label="t('richEditor.moreTools')">
        <q-tooltip>{{ t('richEditor.moreTools') }}</q-tooltip>
        <q-menu v-model="moreOpen"><div class="editorial-toolbar-overflow" @mousedown.prevent>
          <div v-for="group in groups" :key="group.name" role="group" :aria-label="t('richEditor.groups.' + group.name)">
            <div class="editorial-toolbar-title">{{ t('richEditor.groups.' + group.name) }}</div>
            <div v-for="(row, index) in group.rows" :key="index" class="editorial-toolbar-row">
              <EditorialCommand v-for="item in row.filter(item => !mobileKeys.includes(item.key))" :key="item.key" :item="item" :option-active="optionActive" @action="dispatch" />
            </div>
          </div>
        </div></q-menu>
      </q-btn>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import type { Editor } from '@tiptap/core'
import { calloutKinds, type EditorToolbarGroupName } from '../tiptapContent'
import EditorialCommand, { type EditorialCommandItem as Item } from './EditorialCommand.vue'
import ContextSubmenu from './ContextSubmenu.vue'
import pdfIcon from '../icons/bootstrap/file-earmark-pdf-fill.svg?raw'
import zipIcon from '../icons/bootstrap/file-zip-fill.svg?raw'
import { solaire } from '../solaire'
import { editorialIcon } from '../editorialIcons'
import { imageAlignment } from '../imageAlignment'
const { editor, revision, document = false, source = false, findOpen = false, singleRow = false, hiddenGroups = [], fullWidth = false, fullscreen = false, fits = true, disabledActions = [], menu = false } = defineProps<{
  editor: Editor; revision: number; document?: boolean; source?: boolean; findOpen?: boolean; singleRow?: boolean; hiddenGroups?: readonly EditorToolbarGroupName[]; fullWidth?: boolean; fullscreen?: boolean; fits?: boolean; disabledActions?: readonly string[]; menu?: boolean
}>()
const emit = defineEmits<{ action: [key: string, value?: string] }>()
const { t } = useI18n()
const $q = useQuasar()
const moreOpen = ref(false)
const alignments = ['left', 'center', 'right', 'justify'] as const
function dispatch(key: string, value?: string): void {
  moreOpen.value = false
  const alignment = alignments.some(alignment => alignment === key)
  emit('action', alignment ? 'alignment' : key, alignment ? key : value)
}
const mobile = computed(() => $q.screen.lt.md && !singleRow)
function navigateToolbar(event: KeyboardEvent): void {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key) || !(event.target instanceof HTMLButtonElement)) return
  const toolbar = event.currentTarget as HTMLElement
  const buttons = [...toolbar.querySelectorAll<HTMLButtonElement>('button:not([disabled])')].filter(button => button.offsetParent !== null)
  const index = buttons.indexOf(event.target)
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length
  buttons[next]?.focus(); event.preventDefault()
}
const coloredIcon = (svg: string, color: string) => 'img:data:image/svg+xml,' + encodeURIComponent(svg.replaceAll('<path ', `<path fill="${color}" `))
const mobileKeys = ['undo', 'redo', 'bold', 'italic', 'removeFormat', 'heading', 'callout', 'bulletList', 'orderedList', ...alignments, 'galarisLink', 'share.action', 'help']
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
    icon: key === 'exportPdf' ? coloredIcon(pdfIcon, solaire.red.accent)
      : key === 'resources.documentExportBundle' ? coloredIcon(zipIcon, solaire.blue.accent)
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
      ...(document ? [{ ...button('layout.full', 'width_full', fullWidth, true), disabled: !fits }] : [button('source', 'code', source, true)]), button('fullscreen', 'fullscreen', fullscreen, true), ...(document && !$q.screen.lt.md ? [button('help', 'keyboard', false, true)] : []),
    ]] },
    { name: 'editing' as const, rows: [[button('undo', 'undo'), button('redo', 'redo'), button('find', 'search', document ? findOpen : undefined), button('selectAll', 'select_all')], [button('removeFormat', 'format_clear'),
      ...(document ? [$q.screen.lt.md ? button('share.action', 'share', false, true) : button('print', 'print', false, true), button('exportPdf', 'picture_as_pdf', false, true), button('resources.documentExportBundle', 'folder_zip', false, true)] : [])]] },
    { name: 'text' as const, rows: [[
      menu('fontFamily', 'font_download', ['default', 'Arial', 'Georgia', 'Times New Roman', 'Courier New'].map(value => [value === 'default' ? '' : value, value === 'default' ? t('richEditor.defaultFont') : value]), editor.getAttributes('textStyle').fontFamily || t('richEditor.defaultFont')),
      menu('fontSize', 'format_size', ['10', '12', '14', '16', '18', '24', '32', '48'].map(value => [value, value]), String(editor.getAttributes('textStyle').fontSize ?? '').replace('px', '') || '16'),
      ...(['bold', 'italic', 'underline'] as const).map((key, i) => button(key, ['format_bold', 'format_italic', 'format_underlined'][i]!, editor.isActive(key))),
    ], [
      ...(['strike', 'subscript', 'superscript', 'code'] as const).map((key, i) => button(key === 'code' ? 'shortcuts.inlineCode' : key, ['strikethrough_s', 'subscript', 'superscript', 'code'][i]!, editor.isActive(key))),
      button('fontColor', 'format_color_text'), button('backgroundColor', 'format_color_fill'), button('highlight', 'border_color', editor.isActive('highlight')),
    ]] },
    { name: 'paragraph' as const, rows: [[
      heading, ...(document ? [] : [callout]),
      button('bulletList', 'format_list_bulleted', editor.isActive('bulletList')), button('orderedList', 'format_list_numbered', editor.isActive('orderedList')), button('listProperties', 'format_list_numbered_rtl'),
    ], [
      ...alignments.map(value => button(value, 'format_align_' + value, image ? imageAlignment(image) === value : editor.isActive({ textAlign: value }) || value === 'left' && editor.isActive({ textAlign: null }))),
      button('shortcuts.outdent', 'format_indent_decrease'), button('shortcuts.indent', 'format_indent_increase'),
    ]] },
    { name: 'insert' as const, rows: [[button('link', 'link'), button('galarisLink', 'folder_open'), ...(document ? [button('resources.uploadFile', 'upload_file'), button('insertTable', 'table_chart')] : [])],
      ...(document ? [[button('quote', 'format_quote', editor.isActive('blockquote')), button('code', 'code', editor.isActive('codeBlock')), button('separator', 'horizontal_rule'), button('specialCharacters', 'emoji_symbols')]] : [])] },
  ].filter(group => !hiddenGroups.includes(group.name))
})
const contextPrimaryKeys = ['heading', 'bold', 'italic', 'underline', 'removeFormat']
const contextPrimary = computed(() => contextPrimaryKeys.flatMap(key => groups.value.flatMap(group => group.rows.flat()).find(item => item.key === key) ?? []))
const contextGroups = computed(() => groups.value.filter(group => group.name !== 'reading').map(group => ({
  name: group.name,
  items: group.rows.flat().filter(item => !contextPrimaryKeys.includes(item.key) && !['print', 'exportPdf', 'resources.documentExportBundle', 'share.action'].includes(item.key)
    && (item.key !== 'listProperties' || editor.isActive('bulletList') || editor.isActive('orderedList'))),
})).filter(group => group.items.length))
</script>
