<template>
  <q-banner
    v-if="showPrompt"
    rounded
    class="chat-notification-prompt bg-primary text-white shadow-4"
  >
    <template #avatar><q-icon name="notifications_active" /></template>
    <div class="text-weight-medium">{{ t('chat.notifications.promptTitle') }}</div>
    <div class="text-caption">{{ t('chat.notifications.promptBody') }}</div>
    <template #action>
      <q-btn
        flat
        no-caps
        color="white"
        :label="t('chat.notifications.later')"
        @click="snooze"
      />
      <q-btn
        unelevated
        no-caps
        color="white"
        text-color="primary"
        :loading="inbox.loading"
        :label="t('chat.notifications.enable')"
        @click="enable"
      />
    </template>
  </q-banner>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { apiErrorDetail, getStoredAccessToken } from '@/core/api'
import { playChatNotificationSound, unlockChatNotificationSound } from '../notificationSound'
import { useChatStore } from '../stores/chat'
import { useChatInboxStore } from '../stores/inbox'

const SNOOZE_KEY = 'galaris:chat-push-prompt-after'
const SNOOZE_MS = 7 * 24 * 60 * 60 * 1_000

const $q = useQuasar()
const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const chat = useChatStore()
const inbox = useChatInboxStore()
const snoozedUntil = ref(Number(localStorage.getItem(SNOOZE_KEY) || 0))
let retryTimer: number | null = null

const showPrompt = computed(() => (
  inbox.canPrompt
  && Date.now() >= snoozedUntil.value
))

function scheduleStart(): void {
  if (retryTimer !== null) return
  retryTimer = window.setTimeout(() => {
    retryTimer = null
    if (getStoredAccessToken()) void startInbox()
  }, 1_000)
}

async function startInbox(): Promise<void> {
  try {
    await inbox.start()
  } catch {
    scheduleStart()
  }
}

function snooze(): void {
  snoozedUntil.value = Date.now() + SNOOZE_MS
  localStorage.setItem(SNOOZE_KEY, String(snoozedUntil.value))
}

async function enable(): Promise<void> {
  try {
    const enabled = await inbox.enablePush()
    if (enabled) {
      localStorage.removeItem(SNOOZE_KEY)
      snoozedUntil.value = 0
      $q.notify({ type: 'positive', message: t('chat.notifications.enabled') })
    } else if (inbox.permission === 'denied') {
      $q.notify({ type: 'warning', message: t('chat.notifications.denied') })
    }
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: apiErrorDetail(error) ?? t('chat.notifications.enableError'),
    })
  }
}

function unlockSound(): void {
  window.removeEventListener('pointerdown', unlockSound)
  window.removeEventListener('keydown', unlockSound)
  void unlockChatNotificationSound().catch(() => undefined)
}

function roomIsDisplayed(roomId: string): boolean {
  return document.visibilityState === 'visible'
    && route.path === '/chat'
    && chat.selectedRoom?.id === roomId
}

watch(
  () => inbox.inAppNotification?.sequence ?? 0,
  sequence => {
    const notification = inbox.inAppNotification
    if (!sequence || !notification || roomIsDisplayed(notification.roomId)) return
    void playChatNotificationSound().catch(() => undefined)
    $q.notify({
      icon: 'chat',
      color: 'primary',
      message: notification.roomLabel,
      caption: notification.body,
      position: 'top',
      timeout: 8_000,
      actions: [{
        label: t('chat.notifications.open'),
        color: 'white',
        handler: () => void router.push({ path: '/chat', query: { room: notification.roomId } }),
      }],
    })
  },
)

onMounted(() => {
  void startInbox()
  window.addEventListener('pointerdown', unlockSound, { once: true })
  window.addEventListener('keydown', unlockSound, { once: true })
})
onBeforeUnmount(() => {
  if (retryTimer !== null) window.clearTimeout(retryTimer)
  window.removeEventListener('pointerdown', unlockSound)
  window.removeEventListener('keydown', unlockSound)
  inbox.stop()
})
</script>

<style scoped>
.chat-notification-prompt {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 5000;
  width: min(430px, calc(100vw - 32px));
}

@media (max-width: 1023px) {
  .chat-notification-prompt {
    right: 16px;
    bottom: 16px;
  }
}
</style>
