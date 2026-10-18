<template>
  <EditorialToolButton v-if="!item.options" flat dense :icon="item.icon" :label="t('richEditor.' + item.key)" :aria-pressed="item.active" :disable="item.disabled" :color="item.active ? 'primary' : undefined" :class="{ 'editorial-alignment-active': item.active && ['left', 'center', 'right', 'justify'].includes(item.key) }" @click="emit('action', item.key)" />
  <span v-else class="inline-flex">
    <q-btn-dropdown no-caps :flat="!isStyleMenu && (compact || !item.value)" :outline="isStyleMenu || !compact && Boolean(item.value)" dense :icon="!isStyleMenu && (compact || !item.value || item.key === 'fontFamily') ? item.icon : undefined" :label="isStyleMenu || !compact ? item.value : undefined" :aria-label="commandLabel" :disable="item.disabled"
      :class="{ 'editorial-style-selector': isStyleMenu, 'editorial-style-selector--compact': isStyleMenu && compact }"
      :menu-anchor="hasCallouts ? 'bottom middle' : undefined" :menu-self="hasCallouts ? 'top middle' : undefined">
      <q-list dense :class="{ 'editorial-callout-options': hasCallouts }">
        <q-item v-for="option in item.options" :key="(option.action ?? item.key) + ':' + option.value" v-close-popup clickable role="menuitemradio" :aria-label="option.label" :aria-checked="optionActive(option.action ?? item.key, option.value)" @click="emit('action', option.action ?? item.key, option.value)">
          <q-item-section v-if="(option.action ?? item.key) === 'callout'">
            <div class="rich-content editorial-callout-preview">
              <blockquote v-if="option.value" class="galaris-callout" :class="'galaris-callout-' + option.value"><p>{{ option.label }}</p></blockquote>
              <p v-else>{{ option.label }}</p>
            </div>
          </q-item-section>
          <q-item-section v-else :style="optionStyle(option.action ?? item.key, option.value)">{{ option.label }}</q-item-section>
        </q-item>
      </q-list>
    </q-btn-dropdown>
    <q-tooltip>{{ commandLabel }}</q-tooltip>
  </span>
</template>
<script lang="ts">
export interface EditorialCommandItem {
  key: string; icon: string; active?: boolean; disabled?: boolean; value?: string
  options?: Array<{ label: string; value: string; action?: string }>
}
</script>
<style scoped>
.editorial-callout-options { width: min(360px, calc(100vw - 16px)); }
.editorial-callout-preview { min-width: 0; background: transparent; }
.editorial-callout-preview > :is(blockquote, p) { margin: 0; }
.editorial-style-selector { width: 100px; min-width: 100px; max-width: 100px; }
.editorial-style-selector--compact { width: 88px; min-width: 88px; max-width: 88px; }
.editorial-style-selector :deep(.q-btn__content) { flex-wrap: nowrap; }
.editorial-style-selector :deep(.block) { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.editorial-style-selector :deep(.q-btn-dropdown__arrow) { flex-shrink: 0; }
</style>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { computed } from 'vue'
import EditorialToolButton from './EditorialToolButton.vue'
const { item } = defineProps<{
  item: EditorialCommandItem; compact?: boolean
  optionActive: (key: string, value: string) => boolean
}>()
const emit = defineEmits<{ action: [key: string, value?: string] }>()
const { t } = useI18n()
const hasCallouts = computed(() => item.key === 'callout' || item.options?.some(option => option.action === 'callout'))
const isStyleMenu = computed(() => item.key === 'heading' && hasCallouts.value)
const commandLabel = computed(() => t('richEditor.' + (isStyleMenu.value ? 'style' : item.key)))
function optionStyle(key: string, value: string): Record<string, string> {
  if (key === 'fontSize') return { fontSize: value + 'px' }
  if (key === 'heading') return { fontSize: Number(value) ? ['1.8em', '1.5em', '1.3em', '1.1em', '1.1em', '1.1em'][Number(value) - 1]! : '1em' }
  if (key === 'fontFamily' && value) return { fontFamily: value }
  return {}
}
</script>
