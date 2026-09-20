<template>
  <div class="readable-value">
    <span v-if="value == null">—</span>
    <ol v-else-if="Array.isArray(value) && value.length"><li v-for="(entry, index) in value" :key="index"><LabReadableValue :value="entry" /></li></ol>
    <dl v-else-if="typeof value === 'object' && Object.keys(value).length">
      <template v-for="(entry, key) in value" :key="key"><dt>{{ key }}</dt><dd><LabReadableValue :value="entry" /></dd></template>
    </dl>
    <span v-else-if="typeof value === 'object'">—</span>
    <p v-else>{{ value }}</p>
  </div>
</template>
<script setup lang="ts">
defineProps<{ value: unknown }>()
</script>
<style scoped>
.readable-value { overflow-wrap: anywhere; min-width: 0; }
p { white-space: pre-wrap; margin: 0; }
dl, ol { margin: 0; padding: 0; } ol { padding-left: 24px; }
dt { font-weight: 600; margin-top: 8px; } dd { margin: 4px 0 12px 12px; } li { margin-block: 8px; }
</style>
