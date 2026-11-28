<template>
  <q-btn
    flat
    round
    dense
    :aria-label="t('chat.emoji.open')"
    :aria-expanded="open"
    aria-haspopup="dialog"
    aria-keyshortcuts="F2"
  >
    <q-icon name="sentiment_satisfied_alt" size="18px" />
    <q-tooltip>{{ t('chat.emoji.openShortcut', { key: 'F2' }) }}</q-tooltip>
    <q-menu
      ref="pickerMenu"
      v-model="open"
      :anchor="$q.screen.lt.md ? 'top middle' : 'top left'"
      :self="$q.screen.lt.md ? 'bottom middle' : 'bottom left'"
      :offset="[0, 8]"
      :transition-duration="0"
      class="emoji-picker-menu"
      role="dialog"
      :aria-label="t('chat.emoji.title')"
      @before-show="preparePicker"
      @keydown.esc.stop.prevent="open = false"
    >
      <section
        class="emoji-picker"
        :class="{ 'emoji-picker--dark': $q.dark.isActive, 'q-dark': $q.dark.isActive }"
      >
        <div ref="categoryTabs" class="emoji-category-tabs" role="tablist" :aria-label="t('chat.emoji.categories')" @keydown="navigateCategories">
          <q-btn
            v-for="category in categories"
            :key="category.key"
            flat
            round
            dense
            size="md"
            role="tab"
            class="emoji-category-tab"
            :aria-label="categoryLabel(category.key)"
            :aria-selected="activeCategory.key === category.key"
            :tabindex="activeCategory.key === category.key ? 0 : -1"
            :class="{ 'emoji-category-tab--active': activeCategory.key === category.key }"
            @click.stop="activateCategory(category.key)"
          >
            <span class="emoji-category-icon" aria-hidden="true">{{ category.icon }}</span>
            <q-tooltip>{{ categoryLabel(category.key) }}</q-tooltip>
          </q-btn>
        </div>
        <q-separator />
        <div class="emoji-category-title">{{ categoryLabel(activeCategory.key) }}</div>
        <div ref="emojiGrid" class="emoji-grid" role="group" :aria-label="categoryLabel(activeCategory.key)" @keydown="navigateEmojis">
          <q-btn
            v-for="(emoji, index) in activeCategory.emojis"
            :key="`${activeCategory.key}-${index}`"
            flat
            dense
            class="emoji-cell"
            :aria-label="t('chat.emoji.insert', { emoji })"
            :tabindex="focusedEmojiIndex === index ? 0 : -1"
            :data-autofocus="index === 0 ? '' : undefined"
            @focus="focusedEmojiIndex = index"
            @click="selectEmoji(emoji)"
          >
            <span aria-hidden="true">{{ emoji }}</span>
          </q-btn>
        </div>
      </section>
    </q-menu>
  </q-btn>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useTemplateRef } from 'vue'
import { useQuasar, type QMenu } from 'quasar'
import { useI18n } from 'vue-i18n'
import { chatService } from '../services/chatService'
import {
  emojiCategories,
  type EmojiCategory,
  type EmojiCategoryKey,
} from '../emojiCatalog'

const emit = defineEmits<{
  select: [emoji: string]
  error: [error: unknown]
}>()
const $q = useQuasar()
const { t } = useI18n()
const open = defineModel<boolean>({ required: true })
const frequentEmojis = ref<string[]>([])
const displayedFrequentEmojis = ref<string[]>([])
const activeCategoryKey = ref<EmojiCategoryKey>('smileys')
const focusedEmojiIndex = ref(0)
const pickerMenu = useTemplateRef<QMenu>('pickerMenu')
const categoryTabs = useTemplateRef('categoryTabs')
const emojiGrid = useTemplateRef('emojiGrid')
const categories = computed<readonly EmojiCategory[]>(() => {
  if (!displayedFrequentEmojis.value.length) return emojiCategories
  return [
    {
      key: 'frequent',
      icon: '🕘',
      emojis: displayedFrequentEmojis.value,
    },
    ...emojiCategories,
  ]
})
const activeCategory = computed<EmojiCategory>(() => (
  categories.value.find(category => category.key === activeCategoryKey.value)
  ?? emojiCategories[0]!
))
let recordQueue: Promise<void> = Promise.resolve()

function categoryLabel(key: EmojiCategoryKey): string {
  return t(`chat.emoji.category.${key}`)
}

function activateCategory(key: EmojiCategoryKey): void {
  if (activeCategoryKey.value === key) return
  activeCategoryKey.value = key
  focusedEmojiIndex.value = 0
  if (emojiGrid.value) emojiGrid.value.scrollTop = 0
}

function navigateCategories(event: KeyboardEvent): void {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    emojiGrid.value?.querySelector('button')?.focus()
    return
  }
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  event.preventDefault()
  const index = categories.value.findIndex(category => category.key === activeCategoryKey.value)
  const offset = event.key === 'ArrowLeft' ? -1 : 1
  const nextIndex = (index + offset + categories.value.length) % categories.value.length
  const category = categories.value[nextIndex]
  if (!category) return
  activateCategory(category.key)
  categoryTabs.value?.querySelectorAll('button')[nextIndex]?.focus()
}

function navigateEmojis(event: KeyboardEvent): void {
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return
  const grid = emojiGrid.value
  if (!grid) return
  event.preventDefault()
  const buttons = grid.querySelectorAll('button')
  const index = focusedEmojiIndex.value
  // Resolved grid tracks give the same column count as the responsive layout.
  const columns = getComputedStyle(grid).gridTemplateColumns.split(' ').length
  const column = index % columns
  switch (event.key) {
    case 'ArrowLeft':
      if (column > 0) buttons[index - 1]?.focus()
      break
    case 'ArrowRight':
      if (column < columns - 1) buttons[index + 1]?.focus()
      break
    case 'ArrowUp':
      if (index >= columns) buttons[index - columns]?.focus()
      else categoryTabs.value?.querySelector<HTMLButtonElement>('[aria-selected="true"]')?.focus()
      break
    case 'ArrowDown':
      if (index - column + columns < buttons.length) {
        buttons[Math.min(index + columns, buttons.length - 1)]?.focus()
      }
      break
  }
}

function selectEmoji(emoji: string): void {
  open.value = false
  emit('select', emoji)
  recordQueue = recordQueue
    .then(async () => {
      frequentEmojis.value = (await chatService.recordEmojiUse(emoji)).items
    })
    .catch(error => { emit('error', error) })
}

async function loadFrequentEmojis(): Promise<void> {
  try {
    frequentEmojis.value = (await chatService.frequentEmojis()).items
  } catch (error) {
    emit('error', error)
  }
}

async function preparePicker(): Promise<void> {
  // Keep the displayed order stable while the user moves through the picker.
  displayedFrequentEmojis.value = frequentEmojis.value
  if (displayedFrequentEmojis.value.length) activeCategoryKey.value = 'frequent'
  else if (activeCategoryKey.value === 'frequent') activeCategoryKey.value = 'smileys'
  focusedEmojiIndex.value = 0
  recordQueue = recordQueue.then(loadFrequentEmojis)

  await nextTick()
  const grid = emojiGrid.value
  if (!open.value || !grid) return
  // The popup is hidden until positioned. Focus it before Quasar's opening timer finishes.
  pickerMenu.value?.updatePosition()
  await nextTick()
  if (open.value && emojiGrid.value === grid) {
    grid.querySelector('button')?.focus({ preventScroll: true })
  }
}

onMounted(() => { recordQueue = recordQueue.then(loadFrequentEmojis) })
</script>

<style scoped>
.emoji-picker {
  display: flex;
  width: min(400px, calc(100vw - 24px));
  height: min(390px, calc(100dvh - 24px));
  flex-direction: column;
  overflow: hidden;
  color: #2d3440;
  background: #fff;
}

.emoji-category-tabs {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(32px, 1fr));
  gap: 2px;
  padding: 7px;
}

.emoji-category-tabs :deep(.q-btn) {
  width: 100%;
  min-width: 0;
  min-height: 38px;
  border-radius: 8px;
}

.emoji-category-tab--active {
  background: rgba(25, 118, 210, 0.13);
}

.emoji-category-icon {
  font-size: 1.25rem;
  line-height: 1;
}

.emoji-category-title {
  padding: 8px 11px 5px;
  color: #697386;
  font-size: 0.72rem;
  font-weight: 600;
}

.emoji-grid {
  display: grid;
  min-height: 0;
  flex: 1 1 auto;
  align-content: start;
  grid-template-columns: repeat(8, minmax(38px, 1fr));
  gap: 2px;
  overflow-y: auto;
  padding: 2px 7px 9px;
}

.emoji-cell {
  width: 100%;
  min-width: 0;
  min-height: 46px;
  border-radius: 8px;
  font-size: 1.95rem;
  line-height: 1;
}

.emoji-cell:hover,
.emoji-cell:focus-visible {
  background: rgba(25, 118, 210, 0.1);
}

.emoji-picker :is(.emoji-category-tab, .emoji-cell):focus-visible {
  outline: 2px solid var(--solaire-blue-accent) !important;
  outline-offset: -2px;
}

.emoji-picker--dark {
  color: #e3e7ee;
  background: #1b1e23;
}

.emoji-picker--dark .emoji-category-title {
  color: #aeb6c3;
}

.emoji-picker--dark .emoji-category-tab--active,
.emoji-picker--dark .emoji-cell:hover,
.emoji-picker--dark .emoji-cell:focus-visible {
  background: rgba(100, 181, 246, 0.18);
}

@media (max-width: 460px) {
  .emoji-grid {
    grid-template-columns: repeat(7, minmax(0, 1fr));
  }
}
</style>
