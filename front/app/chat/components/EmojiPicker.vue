<template>
  <q-btn
    flat
    round
    dense
    size="sm"
    icon="sentiment_satisfied_alt"
    :aria-label="t('chat.emoji.open')"
  >
    <q-tooltip>{{ t('chat.emoji.open') }}</q-tooltip>
    <q-menu
      v-model="open"
      anchor="top left"
      self="bottom left"
      :offset="[0, 8]"
      class="emoji-picker-menu"
      @before-show="preparePicker"
    >
      <section
        class="emoji-picker"
        :class="{ 'emoji-picker--dark': $q.dark.isActive, 'q-dark': $q.dark.isActive }"
        :aria-label="t('chat.emoji.title')"
      >
        <div class="emoji-category-tabs" role="tablist" :aria-label="t('chat.emoji.categories')">
          <q-btn
            v-for="category in categories"
            :key="category.key"
            flat
            round
            dense
            size="md"
            role="tab"
            :aria-label="categoryLabel(category.key)"
            :aria-selected="activeCategory.key === category.key"
            :class="{ 'emoji-category-tab--active': activeCategory.key === category.key }"
            @click.stop="activeCategoryKey = category.key"
          >
            <span class="emoji-category-icon" aria-hidden="true">{{ category.icon }}</span>
            <q-tooltip>{{ categoryLabel(category.key) }}</q-tooltip>
          </q-btn>
        </div>
        <q-separator />
        <div class="emoji-category-title">{{ categoryLabel(activeCategory.key) }}</div>
        <div class="emoji-grid" role="grid">
          <q-btn
            v-for="(emoji, index) in activeCategory.emojis"
            :key="`${activeCategory.key}-${index}`"
            v-close-popup
            flat
            dense
            class="emoji-cell"
            :aria-label="t('chat.emoji.insert', { emoji })"
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
import { computed, onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
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
const open = ref(false)
const frequentEmojis = ref<string[]>([])
const activeCategoryKey = ref<EmojiCategoryKey>('smileys')
const categories = computed<readonly EmojiCategory[]>(() => {
  if (!frequentEmojis.value.length) return emojiCategories
  return [
    {
      key: 'frequent',
      icon: '🕘',
      emojis: frequentEmojis.value,
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

function selectEmoji(emoji: string): void {
  emit('select', emoji)
  recordQueue = recordQueue
    .then(async () => {
      frequentEmojis.value = (await chatService.recordEmojiUse(emoji)).items
    })
    .catch(error => { emit('error', error) })
}

async function loadFrequentEmojis(preferFrequent: boolean): Promise<void> {
  try {
    frequentEmojis.value = (await chatService.frequentEmojis()).items
    if (preferFrequent && frequentEmojis.value.length) activeCategoryKey.value = 'frequent'
    else if (!frequentEmojis.value.length && activeCategoryKey.value === 'frequent') activeCategoryKey.value = 'smileys'
  } catch (error) {
    emit('error', error)
  }
}

function preparePicker(): void {
  void recordQueue.then(() => loadFrequentEmojis(true))
}

onMounted(() => { void loadFrequentEmojis(true) })
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
    grid-template-columns: repeat(7, minmax(38px, 1fr));
  }
}
</style>
