<template>
  <q-menu v-model="open" no-parent-event @before-show="load">
    <div class="tag-icon-picker q-pa-sm" :class="{ 'tag-icon-picker--dark': $q.dark.isActive }">
      <div class="row items-center no-wrap q-gutter-sm">
        <q-select v-model="family" :options="familyOptions" emit-value map-options dense outlined class="tag-icon-family" :aria-label="t('documents.library.iconCollection')" />
        <q-input v-model="search" autofocus dense outlined clearable class="col" :label="t('documents.library.searchIcons')" @keydown.down.prevent="focusIcon(0)">
          <template #prepend><q-icon name="search" /></template>
        </q-input>
        <q-btn flat round dense :disable="busy" :aria-label="t('documents.library.defaultIcon')" @click="choose(null)">
          <DocumentTagIcon size="24px" :default-icon="defaultIcon" />
          <q-tooltip>{{ t('documents.library.defaultIcon') }}</q-tooltip>
        </q-btn>
        <q-btn flat round dense icon="add" :loading="uploading" :disable="busy" :aria-label="t('documents.library.uploadIcon')" @click="fileInput?.click()">
          <q-tooltip>{{ t('documents.library.uploadIcon') }}</q-tooltip>
        </q-btn>
        <input ref="fileInput" type="file" accept="image/svg+xml,.svg" hidden :aria-label="t('documents.library.uploadIcon')" @change="upload" />
      </div>
      <div v-if="error" role="alert" class="q-my-sm">{{ error }} <q-btn v-if="loadError" flat dense :label="t('documents.retry')" @click="load" /></div>
      <q-linear-progress v-if="loading" indeterminate />
      <div v-if="family === 'emoji'" role="group" :aria-label="t('documents.library.iconCategories')" class="tag-icon-categories q-my-sm">
        <q-btn v-for="group in groups" :key="group.id" flat dense no-caps size="sm" :icon="group.icon"
          :label="t(`documents.library.iconGroups.${group.id}`)" :aria-pressed="category === group.id"
          :class="{ 'tag-icon-category--active': category === group.id }" @click="category = group.id" />
      </div>
      <q-virtual-scroll ref="grid" :key="`${family}:${category}:${columns}:${search}:${locale}`" :items="rows" :virtual-scroll-item-size="48" :virtual-scroll-slice-size="14"
        class="tag-icon-scroll" :aria-label="t('documents.library.iconCollection')">
        <template #default="{ item, index }">
          <div :key="index" class="tag-icon-grid" :style="{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }">
            <button v-for="(icon, column) in item" :key="icon.id" type="button" class="tag-icon-choice" :disabled="busy"
              :data-icon-index="index * columns + Number(column)" :aria-label="icon.name" :title="icon.name" @click="choose(icon.data)"
              @keydown="navigate($event, index * columns + Number(column))">
              <DocumentTagIcon :icon="icon.data" size="32px" />
            </button>
          </div>
        </template>
      </q-virtual-scroll>
      <div v-if="!filtered.length" class="q-pa-sm text-caption">{{ t('documents.library.noIcons') }}</div>
    </div>
  </q-menu>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { QVirtualScroll, useQuasar } from 'quasar'
import { memoryService } from '../services/memoryService'
import type { DocumentTagIcon as UploadedTagIcon } from '../types'
import { loadTagEmojiIcons, type TagEmojiIcon } from '../tagEmojiCatalog'
import { solaireColors } from '@/core/util'
import DocumentTagIcon from './DocumentTagIcon.vue'
const open = defineModel<boolean>({ required: true })
const props = defineProps<{ busy: boolean; save: (icon: string | null) => Promise<boolean>; defaultIcon?: string; document?: boolean }>()
const { t, locale, mergeLocaleMessage } = useI18n()
const $q = useQuasar()
const search = ref<string | null>('')
const family = ref(props.document ? 'emoji' : 'folders')
const familyOptions = computed(() => (props.document ? ['emoji', 'mdi', 'awesome', 'uploaded'] : ['folders', 'emoji', 'mdi', 'awesome', 'uploaded'])
  .map(value => ({ value, label: t(`documents.library.iconFamilies.${value}`) })))
const category = ref('all')
const columns = computed(() => $q.screen.lt.md ? 7 : 9)
const emojis = shallowRef<TagEmojiIcon[]>([])
const groups = [
  { id: 'all', icon: 'apps' }, { id: '0', icon: 'mood' }, { id: '1', icon: 'waving_hand' },
  { id: '3', icon: 'pets' }, { id: '4', icon: 'restaurant' }, { id: '5', icon: 'flight' },
  { id: '6', icon: 'sports_soccer' }, { id: '7', icon: 'lightbulb' }, { id: '8', icon: 'favorite' },
  { id: '9', icon: 'flag' }, { id: '2', icon: 'face' },
]
const grid = useTemplateRef<QVirtualScroll>('grid')
const uploaded = ref<UploadedTagIcon[]>([])
const loading = ref(false)
const uploading = ref(false)
const error = ref('')
const loadError = ref(false)
const fileInput = useTemplateRef<HTMLInputElement>('fileInput')
let disposed = false
let generation = 0
const normalized = (value: string): string => value.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLocaleLowerCase()
const choices = computed(() => [
  ...(family.value === 'uploaded' ? uploaded.value.map(icon => ({ ...icon, group: 'uploaded', tone: 0, keywords: normalized(icon.name) })) : []),
  ...(family.value === 'folders' && !props.document ? solaireColors.map(color => ({
    id: `folder:${color}`, data: `folder:${color}`,
    name: t('documents.library.folderIcon', { color: t(`documents.library.folderColors.${color}`) }),
    group: 'folders', tone: 0, keywords: normalized(`${color} ${t(`documents.library.folderColors.${color}`)}`),
  })) : []),
  ...emojis.value.filter(icon => icon.family === family.value).map(icon => ({
    id: icon.code, name: t(`documentTagEmoji.${icon.code}.name`), group: String(icon.group), tone: icon.tone,
    data: icon.value, keywords: normalized(`${icon.emoji} ${t(`documentTagEmoji.${icon.code}.keywords`)}`),
  })),
])
const filtered = computed(() => {
  const words = normalized(search.value?.trim() ?? '').split(/\s+/).filter(Boolean)
  return choices.value.filter(icon => (family.value !== 'emoji' || category.value === 'all' || icon.group === category.value)
    && icon.tone === 0
    && words.every(word => icon.keywords.includes(word)))
})
const rows = computed(() => Array.from({ length: Math.ceil(filtered.value.length / columns.value) }, (_, row) => filtered.value.slice(row * columns.value, (row + 1) * columns.value)))
async function focusIcon(index: number): Promise<void> {
  if (!filtered.value.length) return
  const target = Math.max(0, Math.min(filtered.value.length - 1, index))
  grid.value?.scrollTo(Math.floor(target / columns.value), 'start')
  await nextTick()
  const element: HTMLElement | undefined = grid.value?.$el
  element?.querySelector<HTMLButtonElement>(`[data-icon-index="${target}"]`)?.focus()
}
function navigate(event: KeyboardEvent, index: number): void {
  const offsets: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: columns.value, ArrowUp: -columns.value, Home: -index, End: filtered.value.length - 1 - index }
  const offset = offsets[event.key]
  if (offset === undefined) return
  event.preventDefault(); void focusIcon(index + offset)
}
async function load(): Promise<void> {
  const current = ++generation
  loading.value = true; error.value = ''; loadError.value = false
  const results = await Promise.allSettled([
    loadTagEmojiIcons((language, messages) => mergeLocaleMessage(language, messages), family.value === 'mdi' || family.value === 'awesome' ? family.value : 'emoji', locale.value),
    memoryService.listDocumentTagIcons(),
  ])
  if (disposed || current !== generation) return
  if (results[0].status === 'fulfilled') emojis.value = results[0].value
  if (results[1].status === 'fulfilled') uploaded.value = results[1].value
  if (results.some(result => result.status === 'rejected')) { error.value = t('documents.library.iconLoadError'); loadError.value = true }
  loading.value = false
}
watch(family, () => { category.value = 'all'; if (open.value) void load() })
watch(locale, () => { if (open.value) void load() })
async function choose(icon: string | null): Promise<void> {
  if (await props.save(icon) && !disposed) open.value = false
}
async function upload(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || uploading.value) return
  error.value = ''; loadError.value = false
  if (!file.name.toLowerCase().endsWith('.svg') || file.size > 64_000) { error.value = t('documents.library.iconUploadError'); return }
  uploading.value = true
  try {
    const data = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result).replace(/^data:[^;]*;/, 'data:image/svg+xml;'))
      reader.onerror = () => reject(reader.error)
      reader.readAsDataURL(file)
    })
    if (disposed) return
    const icon = await memoryService.uploadDocumentTagIcon(file.name.replace(/\.svg$/i, '').slice(0, 100) || file.name, data)
    if (disposed) return
    ++generation; loading.value = false
    uploaded.value = [icon, ...uploaded.value.filter(value => value.id !== icon.id)]
    await choose(icon.data)
  } catch { if (!disposed) error.value = t('documents.library.iconUploadError') }
  finally { if (!disposed) uploading.value = false }
}
onBeforeUnmount(() => { disposed = true; ++generation })
</script>
<style scoped>
.tag-icon-picker { width: min(540px, 94vw); }
.tag-icon-family { flex: 0 1 42%; min-width: 0; }
.tag-icon-categories { display: flex; flex-wrap: wrap; gap: 4px; }
.tag-icon-categories :deep(.q-btn) { padding: 4px 8px; }
.tag-icon-category--active { background: var(--solaire-blue-light); }
.tag-icon-picker--dark .tag-icon-category--active { background: var(--solaire-blue-dark); }
.tag-icon-scroll { height: min(336px, 45vh); overflow: auto; }
.tag-icon-grid { display: grid; height: 48px; gap: 3px; }
.tag-icon-choice { display: grid; place-items: center; border: 0; background: transparent; border-radius: 8px; padding: 4px; cursor: pointer; }
.tag-icon-choice:hover, .tag-icon-choice:focus-visible { background: var(--solaire-blue-light); outline: 2px solid var(--solaire-blue-accent); }
.tag-icon-picker--dark .tag-icon-choice:hover, .tag-icon-picker--dark .tag-icon-choice:focus-visible { background: var(--solaire-blue-dark); }
</style>
