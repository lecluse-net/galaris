/// <reference lib="webworker" />

// Keep this source basename aligned with the historical public URL /sw.js.

import { cleanupOutdatedCaches, createHandlerBoundToURL, precacheAndRoute } from 'workbox-precaching'
import { cacheNames } from 'workbox-core'
import { NavigationRoute, registerRoute } from 'workbox-routing'
import { pwaCacheEnabled } from './cachePolicy'

declare const self: ServiceWorkerGlobalScope & {
  __WB_MANIFEST: Array<{ revision: string | null; url: string }>
}

interface ChatPushPayload {
  title?: string
  body?: string
  icon?: string
  badge?: string
  tag?: string
  unreadCount?: number
  data?: {
    url?: string
    roomId?: string
    messageId?: string
  }
}

const DISPLAYED_ROOM_QUERY = 'galaris:chat-displayed-room-query'
const DISPLAYED_ROOM_RESPONSE = 'galaris:chat-displayed-room-response'
const DISPLAYED_ROOM_RESPONSE_TIMEOUT_MS = 250

// Development keeps push support, but never handles fetches or populates caches.
if (pwaCacheEnabled) {
  const precacheManifest = self.__WB_MANIFEST
  precacheAndRoute(precacheManifest)
  cleanupOutdatedCaches()
  if (precacheManifest.some(entry => entry.url === 'index.html' || entry.url === '/index.html')) {
    registerRoute(new NavigationRoute(createHandlerBoundToURL('index.html'), {
      denylist: [/^\/api\//, /^\/socket\.io\//, /^\/ws\//, /^\/openapi\.json$/],
    }))
  }
}

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', event => event.waitUntil((async () => {
  if (!pwaCacheEnabled) {
    const names = await self.caches.keys()
    await Promise.all(names
      .filter(name => name.startsWith(`${cacheNames.prefix}-`) && name.endsWith(`-${self.registration.scope}`))
      .map(name => self.caches.delete(name)))
  }
  await self.clients.claim()
  // A classic /sw.js can outlive a production-to-development switch. Its old
  // cached HTML cannot load Vite or register /dev-sw.js, even after a refresh.
  // Keep the registration (and push subscription), but reopen its clients online.
  if (!pwaCacheEnabled && self.location.pathname === '/sw.js') {
    const windows = await self.clients.matchAll({ type: 'window' })
    // Navigation waits for this worker to activate. Awaiting it here would keep
    // activation pending forever; closed tabs can safely reject their navigation.
    for (const client of windows) void client.navigate(client.url).catch(() => {})
  }
})()))

async function updateAppBadge(unreadCount: number | undefined): Promise<void> {
  const registration = self.registration as ServiceWorkerRegistration & {
    setAppBadge?: (contents?: number) => Promise<void>
    clearAppBadge?: () => Promise<void>
  }
  if (typeof unreadCount !== 'number') return
  if (unreadCount > 0 && registration.setAppBadge) {
    await registration.setAppBadge(unreadCount)
  } else if (unreadCount === 0 && registration.clearAppBadge) {
    await registration.clearAppBadge()
  }
}

async function clientDisplaysRoom(roomId: string | undefined): Promise<boolean> {
  if (!roomId) return false
  const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
  const visibleWindows = windows.filter(client => client.visibilityState === 'visible')
  const responses = await Promise.all(visibleWindows.map(client => new Promise<boolean>(resolve => {
    const channel = new MessageChannel()
    const timer = self.setTimeout(() => {
      channel.port1.close()
      resolve(false)
    }, DISPLAYED_ROOM_RESPONSE_TIMEOUT_MS)
    channel.port1.onmessage = event => {
      self.clearTimeout(timer)
      channel.port1.close()
      const response = event.data as { type?: unknown; roomId?: unknown } | null
      resolve(
        response?.type === DISPLAYED_ROOM_RESPONSE
        && response.roomId === roomId,
      )
    }
    client.postMessage({ type: DISPLAYED_ROOM_QUERY }, [channel.port2])
  })))
  return responses.some(Boolean)
}

self.addEventListener('push', event => {
  let payload: ChatPushPayload = {}
  try {
    payload = event.data?.json() as ChatPushPayload ?? {}
  } catch {
    payload = { body: event.data?.text() || 'Galaris' }
  }
  const url = payload.data?.url || '/chat'
  event.waitUntil((async () => {
    await updateAppBadge(payload.unreadCount)
    if (await clientDisplaysRoom(payload.data?.roomId)) return
    await self.registration.showNotification(payload.title || 'Galaris', {
      body: payload.body || 'Galaris',
      icon: payload.icon || '/pwa/icon-192.png',
      badge: payload.badge || '/pwa/icon-192.png',
      tag: payload.tag,
      renotify: false,
      data: { ...payload.data, url },
    })
  })())
})

self.addEventListener('notificationclick', event => {
  event.notification.close()
  const rawUrl = (event.notification.data as { url?: string } | undefined)?.url || '/chat'
  const targetUrl = new URL(rawUrl, self.location.origin).href
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    const existing = windows.find(client => new URL(client.url).origin === self.location.origin)
    if (existing) {
      await existing.navigate(targetUrl)
      await existing.focus()
      return
    }
    await self.clients.openWindow(targetUrl)
  })())
})
