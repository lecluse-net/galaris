import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const uri = 'galaris://calendar/9'
const feed = { id: 9, connection_id: 42, agent_id: 7, label: 'Synthetic shared calendar', source_kind: 'internal', timezone: 'Europe/Paris', is_default: true, active: true, writable: true }

for (const width of [390, 1440]) test(`calendar links and discussion attachments open the calendar object at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 950 })
  await jsonRoute(page, '**/api/calendars/9', feed)
  await mount(page, 'core/util/components/RichText.vue', { props: { profile: 'rich-text', agentId: 7, content: `<p><a href="${uri}">Synthetic calendar link</a></p>` }, privileges: ['CALENDAR_ACCESS'] })
  await page.getByRole('link', { name: 'Synthetic calendar link', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText(feed.label)
  await expect(page.getByRole('link', { name: 'Open calendar', exact: true })).toHaveAttribute('href', '/calendar?calendar_id=9&agent_id=7')
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await jsonRoute(page, '**/api/chat/rooms/room-a/messages/calendar-reference/previews', [{
    uri, kind: 'calendar', title: feed.label, media_type: 'application/vnd.galaris.calendar+json', content_format: 'json',
    image_available: false, download_available: false, open_mode: 'inline', metadata: { label: feed.label, agent_id: 7 },
  }])
  await jsonRoute(page, '**/api/chat/rooms/room-a/speech/status*', { available_agent_ids: [] })
  await mount(page, 'app/chat/components/MessageTimeline.vue', { props: {
    roomId: 'room-a', agentId: 7, agentName: 'Synthetic agent', activity: [], liveRound: null,
    messages: [{ id: 'calendar-reference', external_id: 'calendar-reference', room_id: 'room-a', direction: 'outbound', text: 'Synthetic calendar attachment',
      resource_uris: [uri], files: [], sender: null, status: 'sent', is_mine: false, created_at: '2026-11-14T12:00:00Z' }],
  }, privileges: ['CHAT_ACCESS', 'CALENDAR_ACCESS'] })
  await expect(page.getByText(feed.label, { exact: true })).toBeVisible()
  await expect(page.locator('.resource-preview-list img')).toHaveCount(0)
  await page.getByRole('button', { name: `Show preview of ${feed.label}`, exact: true }).first().click()
  await expect(page.getByRole('dialog')).toContainText(feed.label)
})
