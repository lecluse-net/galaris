<template>
  <transition name="scroll-to-bottom">
    <q-btn v-if="visible" class="scroll-to-bottom-button" flat round dense icon="keyboard_arrow_down"
      :aria-label="t('chat.scrollToBottom')" @click="emit('click')">
      <q-tooltip>{{ t('chat.scrollToBottom') }}</q-tooltip>
    </q-btn>
  </transition>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

defineProps<{ visible: boolean }>()
const emit = defineEmits<{ click: [] }>()
const { t } = useI18n()
</script>

<style scoped>
.scroll-to-bottom-button {
  --button-muted: #7c8798;
  --button-surface: #fbfcfe;
  --button-border: rgba(35, 46, 66, .14);
  --button-shadow: rgba(35, 46, 66, .12);
  position: absolute;
  right: 14px;
  bottom: 12px;
  z-index: 2;
  color: var(--chat-text-muted, var(--button-muted));
  background: color-mix(in srgb, var(--chat-surface-raised, var(--button-surface)) 88%, transparent);
  border: 1px solid var(--chat-border-strong, var(--button-border));
  box-shadow: 0 2px 8px color-mix(in srgb, var(--chat-shadow, var(--button-shadow)) 70%, transparent);
  opacity: .78;
  backdrop-filter: blur(5px);
  transition: color .15s ease, opacity .15s ease, background-color .15s ease;
}
body.body--dark .scroll-to-bottom-button {
  --button-muted: #a2adbd;
  --button-surface: #24282f;
  --button-border: rgba(255, 255, 255, .15);
  --button-shadow: rgba(0, 0, 0, .38);
}
.scroll-to-bottom-button:hover,
.scroll-to-bottom-button:focus-visible {
  color: var(--q-primary);
  background: var(--chat-surface-raised, var(--button-surface));
  opacity: 1;
}
.scroll-to-bottom-enter-active,
.scroll-to-bottom-leave-active { transition: opacity .15s ease, transform .15s ease; }
.scroll-to-bottom-enter-from,
.scroll-to-bottom-leave-to { opacity: 0; transform: translateY(6px); }
</style>
