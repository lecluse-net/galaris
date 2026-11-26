<template>
  <ul v-if="labels?.length" class="user-membership-labels">
    <li v-for="item in labels" :key="item.id">
      <q-chip dense class="user-membership-chip">{{ item.label }}</q-chip>
    </li>
  </ul>
  <span v-else-if="labels" class="text-caption">{{ emptyLabel }}</span>
</template>

<script setup lang="ts">
defineProps<{
  labels: { id: number; label: string }[] | undefined
  emptyLabel: string
}>()
</script>

<style scoped>
.user-membership-labels {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 0;
  margin: 0;
  list-style: none;
}

.user-membership-labels li {
  min-width: 0;
  max-width: 100%;
}

.user-membership-chip {
  height: auto;
  min-height: 20px;
  max-width: 100%;
  margin: 0;
  background: var(--solaire-gray-light);
  color: inherit;
}

.body--dark .user-membership-chip {
  background: var(--solaire-gray-dark);
}

.user-membership-chip :deep(.q-chip__content) {
  white-space: normal;
  overflow-wrap: anywhere;
}
</style>
