<template>
  <q-dialog v-model="open">
    <q-card class="conversation-turn-dialog galaris-detail-dialog">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <q-icon :name="icon" size="sm" class="q-mr-sm" />
        <div class="text-h6 ellipsis">{{ title }}</div>
        <q-space />
        <q-btn
          v-close-popup
          flat
          round
          dense
          icon="close"
          :aria-label="closeLabel"
        />
      </q-card-section>
      <q-separator />
      <slot />
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
const open = defineModel<boolean>({ required: true })
defineProps<{
  title: string
  closeLabel: string
  icon: string
}>()
</script>

<style scoped>
.conversation-turn-dialog {
  overflow-y: auto;
}
</style>
