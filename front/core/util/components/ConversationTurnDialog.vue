<template>
  <q-dialog v-model="open">
    <q-card class="conversation-turn-dialog galaris-detail-dialog galaris-dialog-card" :style="{ width }">
      <DialogHeader :title="title" :icon="icon" :close-label="closeLabel" />
      <q-separator />
      <div class="galaris-dialog-body">
        <slot />
      </div>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import DialogHeader from './DialogHeader.vue'
const open = defineModel<boolean>({ required: true })
defineProps<{
  title: string
  closeLabel: string
  icon: string
  width?: string
}>()
</script>
