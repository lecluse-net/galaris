import { test, expect, mount, jsonRoute, editorHtml, setPrivileges } from './fixtures.mjs'
import { document } from './data.mjs'

const id = '00000000-0000-4000-8000-000000000821'
const topics = [{ id: 'topic-a', title: 'Synthetic gardening' }, { id: 'topic-b', title: 'Synthetic plants' }]

for (const kind of ['document', 'dataset']) for (const width of [1440, 390]) {
  test(`${kind} topic changes preserve the draft and reopen the shared audit at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    const initialTopic = width === 390 ? null : 'topic-a'
    let currentTopic = initialTopic, version = 3, fail = true
    const changes = []
    await jsonRoute(page, '**/api/topics/refs?*', topics)
    await jsonRoute(page, '**/api/topics?*', { items: topics, total: 2, month: '2026-10', available_months: [] })
    for (const topic of topics) await jsonRoute(page, `**/api/topics/${topic.id}`, topic)
    await page.route('**/api/dream/topic-assignment?*', route => route.fulfill({ json: {
      topic_id: currentTopic, subject_kind: kind, subject_id: id, origin: currentTopic === 'topic-a' ? 'dream' : 'manual',
      reason: 'Synthetic classification reason', action: 'reuse', confidence: 0.9, human_confirmed: false,
      dream_receipt_id: null, decided_at: null,
    } }))
    await page.route(`**/api/topics/resources/${kind}/${id}`, route => {
      changes.push(route.request().postDataJSON())
      if (fail) return route.fulfill({ status: 409, json: { detail: 'Synthetic assignment conflict' } })
      currentTopic = changes.at(-1).topic_id; version++
      return route.fulfill({ json: { topic_id: currentTopic, lock_version: version } })
    })
    if (kind === 'document') {
      await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [{ id: 7, label: 'Alice', kind: 'agent' }], users: [] })
      await jsonRoute(page, `**/api/documents/${id}/attachments?*`, [])
      await jsonRoute(page, '**/api/documents/keywords*', [])
      await jsonRoute(page, '**/api/agents?*', [])
      await page.route(`**/api/documents/${id}?*`, route => {
        if (route.request().method() !== 'PATCH') return route.fulfill({ json: { item: { ...document, id, topic_id: currentTopic } } })
        const body = route.request().postDataJSON(); version++
        return route.fulfill({ json: { ...document, id, topic_id: currentTopic,
          payload: body.payload || { text: '<p>Synthetic document draft</p>' }, revision: 4, lock_version: version } })
      })
      await mount(page, 'app/document/components/DocumentEditor.vue', {
        props: { documentId: id, agentId: 7, initialDocument: { ...document, id, topic_id: currentTopic,
          media_type: 'text/html', payload: { text: '<p>Synthetic document body</p>' } } },
        privileges: ['DOCUMENT_EDIT', 'TOPIC_EDIT', 'TOPIC_ACCESS'],
      })
      await page.locator('[data-editor-surface]').fill('Synthetic document draft')
    } else {
      await jsonRoute(page, `**/api/datasets/${id}`, { id, uri: `data://${id}`, title: 'Synthetic Dataset',
        topic_id: currentTopic, lock_version: version, revision: 1, content: '{"quantity":3}',
        can_write: true, can_manage: false, can_delete: false, keywords: [], read_only: false })
      await jsonRoute(page, `**/api/datasets/${id}/owner`, { owner: null, options: [] })
      await jsonRoute(page, `**/api/datasets/${id}/sharing`, { lock_version: version, can_manage: false,
        level: 'private', grants: [], options: [], owner: null, owner_groups: [] })
      await mount(page, 'app/dataset/components/DatasetEditor.vue', { props: { id }, privileges: ['DATASET_EDIT', 'TOPIC_EDIT', 'TOPIC_ACCESS'] })
      await page.getByRole('textbox', { name: 'JSON content', exact: true }).fill('{ "unsaved":')
    }
    await page.getByRole('button', { name: `View the origin of the assignment to dossier “${initialTopic ? 'Synthetic gardening' : 'No topic'}”`, exact: true }).click()
    const audit = page.getByRole('dialog').last()
    if (initialTopic) await expect(audit.getByText('Synthetic classification reason', { exact: true })).toBeVisible()
    await audit.getByRole('combobox').click()
    await page.getByRole('option', { name: 'Synthetic plants', exact: true }).click()
    await audit.getByRole('button', { name: 'Save dossier', exact: true }).click()
    await expect(audit.getByRole('alert').filter({ hasText: 'Synthetic assignment conflict' })).toBeVisible()
    fail = false
    await audit.getByRole('button', { name: 'Save dossier', exact: true }).click()
    await expect(audit).toHaveCount(0)
    expect(changes).toHaveLength(2)
    expect(changes.at(-1)).toMatchObject({ topic_id: 'topic-b', expected_topic_id: initialTopic })
    if (kind === 'dataset') await expect(page.getByRole('textbox', { name: 'JSON content', exact: true })).toHaveValue('{ "unsaved":')
    else expect(await editorHtml(page)).toContain('Synthetic document draft')
    await page.screenshot({ path: testInfo.outputPath(`${kind}-topic-header.png`), animations: 'disabled' })
    await page.getByRole('button', { name: 'View the origin of the assignment to dossier “Synthetic plants”', exact: true }).click()
    await expect(page.getByRole('dialog').getByRole('alert')).toContainText('This assignment does not match any recorded Dream decision')
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.getByRole('dialog').evaluate(async element => {
      await Promise.all(element.getAnimations({ subtree: true }).filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity)
        .map(animation => animation.finished.catch(() => {})))
    })
    await page.screenshot({ path: testInfo.outputPath(`${kind}-topic-audit.png`), animations: 'disabled' })
    await page.keyboard.press('Escape')
    await setPrivileges(page, [kind === 'document' ? 'DOCUMENT_EDIT' : 'DATASET_EDIT', 'TOPIC_ACCESS'])
    await page.getByRole('button', { name: 'View the origin of the assignment to dossier “Synthetic plants”', exact: true }).click()
    await expect(page.getByRole('dialog').getByRole('button', { name: 'Save dossier', exact: true })).toHaveCount(0)
  })
}
