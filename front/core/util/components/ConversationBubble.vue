<template>
  <div
    class="row conversation-bubble-row"
    :class="[
      `conversation-bubble-row--${side}`,
      side === 'outgoing' ? 'justify-end' : 'justify-start',
    ]"
  >
    <div class="conversation-bubble-column">
      <div
        class="conversation-bubble-speaker text-grey-7 q-mb-xs"
        :class="{ 'text-right': side === 'outgoing' }"
      >
        {{ speaker.trim() }}
      </div>
      <div
        class="conversation-bubble"
        :class="[
          `conversation-bubble--${side}`,
          `conversation-bubble--${contentMode}`,
        ]"
      >
        <slot />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
const {
  speaker,
  side = 'incoming',
  contentMode = 'plain',
} = defineProps<{
  speaker: string
  side?: 'incoming' | 'outgoing'
  contentMode?: 'plain' | 'rich'
}>()
</script>

<style scoped>
.conversation-bubble-row {
  width: 100%;
  box-sizing: border-box;
  padding-inline: 16px;
}

.conversation-bubble-row--incoming {
  padding-inline-start: 0;
}

.conversation-bubble-column {
  width: fit-content;
  max-width: min(86%, 760px);
  min-width: 0;
}

.conversation-bubble {
  color: #000;
  font-family: inherit;
  font-size: 14px;
  font-weight: 400;
  line-height: 1.5;
  padding: 12px 16px;
  border: 1px solid rgb(0 0 0 / 10%);
  border-radius: 16px;
  overflow-wrap: anywhere;
  box-shadow: 0 1px 2px rgb(0 0 0 / 5%);
}

.conversation-bubble-speaker {
  font-family: inherit;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.35;
}

.conversation-bubble--plain {
  white-space: pre-wrap;
}

.conversation-bubble--rich {
  white-space: normal;
}

.conversation-bubble--incoming {
  background: #f5f5f5;
  border-top-left-radius: 5px;
}

.conversation-bubble--outgoing {
  background: #e3f2fd;
  border-color: rgb(25 118 210 / 16%);
  border-top-right-radius: 5px;
}

.conversation-bubble--rich :deep(.markdown-content p) {
  color: inherit;
  font: inherit;
  margin: 0 0 0.45em;
}

.conversation-bubble--rich :deep(.markdown-content li) {
  color: inherit;
  font: inherit;
}

.conversation-bubble--rich :deep(.markdown-content blockquote) {
  color: inherit;
}

body.body--dark .conversation-bubble-speaker {
  color: #bdbdbd !important;
}

body.body--dark .conversation-bubble {
  color: #f5f5f5;
  border-color: rgb(255 255 255 / 14%);
  box-shadow: 0 1px 2px rgb(0 0 0 / 30%);
}

body.body--dark .conversation-bubble--incoming {
  background: #303030;
}

body.body--dark .conversation-bubble--outgoing {
  background: #183b56;
  border-color: rgb(100 181 246 / 28%);
}

body.body--dark .conversation-bubble--rich :deep(.markdown-content blockquote) {
  color: inherit;
}

.conversation-bubble--rich :deep(.markdown-content p:first-child) {
  margin-top: 0;
}

.conversation-bubble--rich :deep(.markdown-content p:last-child) {
  margin-bottom: 0;
}

@media (max-width: 599px) {
  .conversation-bubble-row {
    padding-inline: 8px;
  }

  .conversation-bubble-row--incoming {
    padding-inline-start: 0;
  }

  .conversation-bubble-column {
    max-width: 94%;
  }
}
</style>
