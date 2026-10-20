<template>
  <section v-for="id in ['first', 'second']" :key="id" class="menu-row" tabindex="0" :aria-label="id">
    <p>{{ id }} selectable text</p>
    <ActionContextMenu target=".menu-row" :label="id" :preserve-selection="preserveSelection" :actions="actions(id)" />
    <span>{{ counts[id] ?? 0 }}</span>
  </section>
  <q-btn outline label="Outside action" @pointerdown.stop @mousedown.stop @click.stop="outside++" />
  <p role="status">{{ outside }}</p>
  <input aria-label="Outside input">
  <iframe title="Outside frame" sandbox="allow-scripts" srcdoc="<button onclick=&quot;this.textContent='Frame clicked'&quot;>Frame action</button>" />
</template>
<script setup lang="ts">
import { reactive, ref } from 'vue'
import ActionContextMenu from '@/core/util/components/ActionContextMenu.vue'
const { disabled = false, preserveSelection = false, fail = false } = defineProps<{ disabled?: boolean; preserveSelection?: boolean; fail?: boolean }>()
const counts = reactive<Record<string, number>>({})
const outside = ref(0)
function actions(id: string) {
  return [{ key: 'apply', icon: 'edit', label: 'Apply', disabled, run: async () => {
    if (fail) throw new Error('Synthetic failure')
    counts[id] = (counts[id] ?? 0) + 1
  } }]
}
</script>
