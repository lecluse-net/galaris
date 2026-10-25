import { test, expect, mount, jsonRoute } from './fixtures.mjs'

for (const width of [390, 1440]) {
  test(`voice text appears in the listening bubble and hands off once at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await jsonRoute(page, '**/api/chat/rooms/*/speech/status*', { available_agent_ids: [] })
    const pending = {
      id: 'synthetic-transcription', room_id: 'synthetic-room',
      started_at: '2026-10-01T12:00:00Z', message_id: null, text: '',
      sender: { display_name: 'Synthetic caller', is_ai: false }, is_mine: true,
    }
    await mount(page, 'app/chat/components/MessageTimeline.vue', {
      props: { roomId: pending.room_id, messages: [], activity: [], liveRound: null,
        pendingTranscriptions: [pending], agentId: 7, agentName: 'Synthetic agent', showAgentAvatars: false },
    })
    await expect(page.getByRole('status')).toContainText('Listening')
    for (const text of ['Hello', 'Hello world <example>']) {
      await page.evaluate(pending => window.testApp.setProps({ pendingTranscriptions: [pending] }), { ...pending, text })
      await expect(page.locator('.message-text')).toHaveText(text)
      await expect(page.locator('.message-row')).toHaveCount(1)
    }
    await page.screenshot({ path: `/artifacts/chat-transcription-${width}.png` })
    await page.evaluate(pending => window.testApp.setProps({
      pendingTranscriptions: [], messages: [{
        id: 'synthetic-message', external_id: 'synthetic-message', text: 'Hello world',
        sender: pending.sender, is_mine: true, files: [], created_at: pending.started_at,
      }],
    }), pending)
    await expect(page.getByRole('status')).toHaveCount(0)
    await expect(page.locator('.message-text')).toHaveText('Hello world')
    await expect(page.locator('.message-row')).toHaveCount(1)
  })
}
