import { computed, ref, onScopeDispose } from 'vue'
import { defineStore } from 'pinia'
import { AUTH_TOKEN_CHANGED_EVENT, getStoredAccessToken, registerBeforeLogoutHook, sessionGeneration } from '@/core/api'
import { websocket } from '@/core/websocket'
import { chatService } from '../services/chatService'
import type { MessengerRoom, PushConfiguration, PushSubscriptionPayload, RealtimeMessageEvent } from '../types'

interface InAppChatNotification {
  sequence: number
  roomId: string
  messageId: string
  roomLabel: string
  body: string
}

const NOTIFIED_PREFIX = 'galaris:chat-notified:'
const NOTIFIED_TTL_MS = 24 * 60 * 60 * 1_000
const FALLBACK_DELAY_MS = 3_200
const NOTIFICATION_PREVIEW_MAX_CHARS = 96
const DISPLAYED_ROOM_QUERY = 'galaris:chat-displayed-room-query'
const DISPLAYED_ROOM_RESPONSE = 'galaris:chat-displayed-room-response'

function pushSupportedByBrowser(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

function applicationServerKey(value: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - value.length % 4) % 4)
  const decoded = atob((value + padding).replace(/-/g, '+').replace(/_/g, '/'))
  const bytes = new Uint8Array(new ArrayBuffer(decoded.length))
  for (let index = 0; index < decoded.length; index += 1) bytes[index] = decoded.charCodeAt(index)
  return bytes
}

function subscriptionPayload(subscription: PushSubscription): PushSubscriptionPayload {
  const json = subscription.toJSON()
  const p256dh = json.keys?.p256dh
  const auth = json.keys?.auth
  if (!json.endpoint || !p256dh || !auth) throw new Error('Incomplete Web Push subscription')
  return {
    endpoint: json.endpoint,
    expiration_time: json.expirationTime ?? null,
    keys: { p256dh, auth },
  }
}

async function setApplicationBadge(count: number): Promise<void> {
  const badgeNavigator = navigator as Navigator & {
    setAppBadge?: (contents?: number) => Promise<void>
    clearAppBadge?: () => Promise<void>
  }
  if (count > 0 && badgeNavigator.setAppBadge) await badgeNavigator.setAppBadge(count)
  else if (count === 0 && badgeNavigator.clearAppBadge) await badgeNavigator.clearAppBadge()
}

function claimInAppNotification(messageId: string): boolean {
  const key = `${NOTIFIED_PREFIX}${messageId}`
  const previous = Number(localStorage.getItem(key) || 0)
  const now = Date.now()
  if (previous > now - NOTIFIED_TTL_MS) return false
  localStorage.setItem(key, String(now))
  return true
}

function notificationPreview(text: string): string {
  const normalized = text.trim().replace(/\n/g, ' ')
  if (normalized.length <= NOTIFICATION_PREVIEW_MAX_CHARS) return normalized
  return `${normalized.slice(0, NOTIFICATION_PREVIEW_MAX_CHARS - 1).trimEnd()}…`
}

export const useChatInboxStore = defineStore('chatInbox', () => {
  let summaryRequest = 0
  let lifecycleGeneration = 0
  const unreadCount = ref(0)
  const configuration = ref<PushConfiguration | null>(null)
  const subscribed = ref(false)
  const permission = ref<NotificationPermission>(
    'Notification' in window ? Notification.permission : 'denied',
  )
  const inAppNotification = ref<InAppChatNotification | null>(null)
  const displayedRoomId = ref<string | null>(null)
  const started = ref(false)
  const loading = ref(false)
  const fallbackTimers = new Map<string, number>()
  let notificationSequence = 0
  let unregisterLogoutHook: (() => void) | null = null

  const pushSupported = computed(() => pushSupportedByBrowser())
  const pushAvailable = computed(() => configuration.value?.available === true)
  const canPrompt = computed(() => (
    pushSupported.value
    && pushAvailable.value
    && permission.value === 'default'
    && !subscribed.value
  ))

  async function refreshSummary(): Promise<void> {
    const request = ++summaryRequest
    const session = sessionGeneration()
    const summary = await chatService.inbox()
    if (request !== summaryRequest || session !== sessionGeneration()) return
    unreadCount.value = summary.unread_count
    await setApplicationBadge(summary.unread_count)
  }

  async function currentSubscription(): Promise<PushSubscription | null> {
    // No subscription can be used before the browser grants notification access.
    // Avoid waiting for a worker (or waking the platform push service) otherwise.
    if (!pushSupported.value || Notification.permission !== 'granted') return null
    const registration = await navigator.serviceWorker.ready
    return registration.pushManager.getSubscription()
  }

  async function synchronizeSubscription(): Promise<void> {
    const lifecycle = lifecycleGeneration
    const session = sessionGeneration()
    const config = await chatService.pushConfiguration()
    if (lifecycle !== lifecycleGeneration || session !== sessionGeneration()) return
    configuration.value = config
    permission.value = 'Notification' in window ? Notification.permission : 'denied'
    const subscription = await currentSubscription()
    if (lifecycle !== lifecycleGeneration || session !== sessionGeneration()) return
    subscribed.value = subscription !== null
    if (subscription && configuration.value.available) {
      await chatService.registerPushSubscription(subscriptionPayload(subscription))
    }
  }

  async function enablePush(): Promise<boolean> {
    if (!pushSupported.value) return false
    loading.value = true
    try {
      configuration.value ??= await chatService.pushConfiguration()
      if (!configuration.value.available || !configuration.value.public_key) return false
      permission.value = await Notification.requestPermission()
      if (permission.value !== 'granted') return false
      const registration = await navigator.serviceWorker.ready
      const existing = await registration.pushManager.getSubscription()
      const subscription = existing ?? await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: applicationServerKey(configuration.value.public_key),
      })
      await chatService.registerPushSubscription(subscriptionPayload(subscription))
      subscribed.value = true
      return true
    } finally {
      loading.value = false
    }
  }

  async function disablePush(): Promise<void> {
    if (!pushSupported.value) return
    const session = sessionGeneration()
    loading.value = true
    try {
      const subscription = await currentSubscription()
      if (session !== sessionGeneration()) return
      if (!subscription) {
        subscribed.value = false
        return
      }
      try {
        if (getStoredAccessToken()) await chatService.deletePushSubscription(subscription.endpoint)
      } finally {
        if (session === sessionGeneration()) {
          await subscription.unsubscribe()
          subscribed.value = false
        }
      }
    } finally {
      loading.value = false
    }
  }

  async function notifyInApp(roomId: string, messageId: string): Promise<void> {
    const lifecycle = lifecycleGeneration
    const session = sessionGeneration()
    await refreshSummary()
    if (lifecycle !== lifecycleGeneration || session !== sessionGeneration()) return
    if (displayedRoomId.value === roomId) return
    const subscription = await currentSubscription()
    if (lifecycle !== lifecycleGeneration || session !== sessionGeneration()) return
    subscribed.value = subscription !== null
    if (subscription) return
    let room: MessengerRoom
    try {
      room = await chatService.room(roomId)
    } catch {
      return
    }
    const message = room.last_message
    if (lifecycle !== lifecycleGeneration || session !== sessionGeneration()) return
    if (
      room.muted
      || room.unread_count === 0
      || message?.id !== messageId
      || message.is_mine
      || displayedRoomId.value === roomId
      || !claimInAppNotification(messageId)
    ) return
    notificationSequence += 1
    inAppNotification.value = {
      sequence: notificationSequence,
      roomId,
      messageId,
      roomLabel: room.label,
      body: room.show_last_message && message.text.trim()
        ? notificationPreview(message.text)
        : message.sender?.display_name || room.label,
    }
  }

  function setDisplayedRoom(roomId: string | null): void {
    displayedRoomId.value = roomId
    if (roomId !== null && inAppNotification.value?.roomId === roomId) {
      inAppNotification.value = null
    }
  }

  function onServiceWorkerMessage(event: MessageEvent<unknown>): void {
    if (
      typeof event.data !== 'object'
      || event.data === null
      || !('type' in event.data)
      || event.data.type !== DISPLAYED_ROOM_QUERY
    ) return
    event.ports[0]?.postMessage({
      type: DISPLAYED_ROOM_RESPONSE,
      roomId: displayedRoomId.value,
    })
  }

  function onMessage(event: RealtimeMessageEvent): void {
    const roomId = event.data?.room_id
    const messageId = event.data?.message_id
    if (!roomId || !messageId || event.data?.is_new !== true) {
      void refreshSummary().catch(() => undefined)
      return
    }
    const existing = fallbackTimers.get(messageId)
    if (existing !== undefined) window.clearTimeout(existing)
    fallbackTimers.set(messageId, window.setTimeout(() => {
      fallbackTimers.delete(messageId)
      void notifyInApp(roomId, messageId).catch(() => undefined)
    }, FALLBACK_DELAY_MS))
  }

  function onConnect(): void {
    void refreshSummary().catch(() => undefined)
  }

  function onAuthChanged(event: Event): void {
    const token = (event as CustomEvent<string | null>).detail
    if (!token) stop()
  }

  async function start(): Promise<void> {
    if (started.value || !getStoredAccessToken()) return
    started.value = true
    const lifecycle = ++lifecycleGeneration
    websocket.createWebsocket()
    websocket.onEvent('chat', 'message', onMessage)
    websocket.onConnect(onConnect)
    window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, onAuthChanged)
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.addEventListener('message', onServiceWorkerMessage)
    }
    unregisterLogoutHook = registerBeforeLogoutHook(disablePush)
    try {
      await Promise.all([
        refreshSummary(),
        synchronizeSubscription(),
      ])
    } catch (error) {
      if (lifecycle !== lifecycleGeneration) return
      stop()
      throw error
    }
  }

  function stop(): void {
    lifecycleGeneration++
    summaryRequest++
    if (!started.value) return
    websocket.offEvent('chat', 'message', onMessage)
    websocket.offConnect(onConnect)
    window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, onAuthChanged)
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.removeEventListener('message', onServiceWorkerMessage)
    }
    for (const timer of fallbackTimers.values()) window.clearTimeout(timer)
    fallbackTimers.clear()
    unregisterLogoutHook?.()
    unregisterLogoutHook = null
    started.value = false
    unreadCount.value = 0
    inAppNotification.value = null
    void setApplicationBadge(0)
  }

  onScopeDispose(stop)

  return {
    unreadCount,
    configuration,
    subscribed,
    permission,
    inAppNotification,
    displayedRoomId,
    started,
    loading,
    pushSupported,
    pushAvailable,
    canPrompt,
    start,
    stop,
    refreshSummary,
    synchronizeSubscription,
    enablePush,
    disablePush,
    setDisplayedRoom,
  }
})
