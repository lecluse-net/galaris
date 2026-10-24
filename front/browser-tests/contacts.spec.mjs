import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'
import { agent } from './data.mjs'

const component = 'app/memory/pages/contacts.vue'
const initial = {
  memory_item_id: '10000000-0000-4000-8000-000000000001', owner_agent_id: 7,
  display_name: 'Synthetic contact', memory_title: 'Contact — Synthetic contact',
  identities: [
    { id: '10000000-0000-4000-8000-000000000002', kind: 'messenger', namespace: 'matrix', external_id: '@synthetic:example.test', display_name: 'Remote name', galaris_user_id: null },
    { id: '10000000-0000-4000-8000-000000000003', kind: 'messenger', namespace: 'mail', external_id: 'alias@example.org', display_name: 'Mail alias', galaris_user_id: null },
  ],
  linked_memory_count: 3, created_at: '2026-01-01T12:00:00Z', updated_at: null,
}

async function fixtures(page) {
  await jsonRoute(page, '**/api/agents?*', [agent, { ...agent, id: 8, first_name: 'Bob' }])
  await jsonRoute(page, '**/api/agents/selection?*', [
    { id: 7, label: 'Alice Example', has_avatar: false }, { id: 8, label: 'Bob Example', has_avatar: false },
  ])
  const contacts = [structuredClone(initial)]
  await page.route('**/api/contacts?*', route => {
    const visible = new URL(route.request().url()).searchParams.get('agent_id') === '7' ? contacts : []
    return route.fulfill({ json: { items: visible, total: visible.length, limit: 50, offset: 0, has_more: false } })
  })
  return {
    update: updated => { contacts[0] = { ...contacts[0], ...updated } },
    add: contact => { contacts.push(contact) },
  }
}

// The former arbitrary identity/catalogue scenarios now exercise non-destructive
// splitting; existing associations can only be combined through checkbox/merge.
for (const mobile of [false, true]) {
  test(`contact splitting preserves a failed draft on ${mobile ? 'mobile' : 'desktop'}`, async ({ page }) => {
    if (mobile) await page.setViewportSize({ width: 390, height: 844 })
    const contacts = await fixtures(page)
    const writes = []
    await page.route(`**/api/contacts/${initial.memory_item_id}`, route => {
      const body = route.request().postDataJSON()
      writes.push(body)
      if (writes.length === 1) return route.fulfill({ status: 503, json: { detail: 'Synthetic temporary failure' } })
      const identities = initial.identities.filter(identity => !body.split_identity_ids.includes(identity.id))
      const saved = { ...initial, display_name: body.display_name, identities }
      contacts.update(saved)
      contacts.add({ ...initial, memory_item_id: '10000000-0000-4000-8000-000000000099',
        display_name: body.display_name, identities: [initial.identities[1]], linked_memory_count: 0 })
      return route.fulfill({ json: saved })
    })
    await mount(page, component, { privileges: ['CONTACT_EDIT'] })
    await page.getByText('Synthetic contact', { exact: true }).click()
    const dialog = page.getByRole('dialog')
    const name = dialog.getByLabel('Display name', { exact: true })
    await name.fill('')
    await expect(dialog.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
    await name.fill('Edited contact')
    await dialog.getByRole('button', { name: 'Split identity 2', exact: true }).click()
    await expect(dialog.getByText('This identity will have its own contact after saving.', { exact: true })).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Split identity 1', exact: true })).toBeDisabled()
    await dialog.getByRole('button', { name: 'Undo split of identity 2', exact: true }).click()
    await expect(dialog.getByRole('button', { name: 'Split identity 1', exact: true })).toBeEnabled()
    await dialog.getByRole('button', { name: 'Split identity 2', exact: true }).focus()
    await page.keyboard.press('Enter')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog.getByRole('alert').filter({ hasText: 'The contact could not be updated.' })).toContainText('Synthetic temporary failure')
    await expect(name).toHaveValue('Edited contact')
    await expect(dialog.getByRole('button', { name: 'Undo split of identity 2', exact: true })).toBeEnabled()
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(writes[0]).toEqual(writes[1])
    expect(writes[1]).toEqual({ display_name: 'Edited contact', split_identity_ids: [initial.identities[1].id],
      expected_identity_ids: initial.identities.map(identity => identity.id) })
    await expect(page.getByRole('button', { name: 'Edit contact Edited contact', exact: true })).toHaveCount(2)
    await page.getByRole('button', { name: 'Edit contact Edited contact', exact: true }).first().click()
    await expect(name).toHaveValue('Edited contact')
    await expect(dialog.getByRole('button', { name: 'Split identity 1', exact: true })).toBeDisabled()
    await dialog.getByRole('button', { name: 'Save', exact: true }).hover()
    await page.screenshot({ path: `/artifacts/contacts-${mobile ? 'mobile' : 'desktop'}.png`, animations: 'disabled' })
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
  })

  test(`an external email contact can be created and retried on ${mobile ? 'mobile' : 'desktop'}`, async ({ page }) => {
    if (mobile) await page.setViewportSize({ width: 390, height: 844 })
    const contacts = await fixtures(page)
    const writes = []
    await page.route('**/api/contacts', route => {
      const body = route.request().postDataJSON()
      writes.push(body)
      if (writes.length === 1) return route.fulfill({ status: 409, json: { detail: 'Synthetic address conflict' } })
      const created = { ...initial, memory_item_id: '10000000-0000-4000-8000-000000000099',
        display_name: body.display_name, linked_memory_count: 0,
        identities: [{ ...initial.identities[1], external_id: body.email, display_name: '' }] }
      contacts.add(created)
      return route.fulfill({ status: 201, json: created })
    })
    await mount(page, component, { privileges: ['CONTACT_EDIT'] })
    await page.getByRole('button', { name: 'Add email contact', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('button', { name: 'Create contact', exact: true })).toBeDisabled()
    await dialog.getByLabel('Display name', { exact: true }).fill('External correspondent')
    await dialog.getByLabel('Email address', { exact: true }).fill('outside@example.org')
    await dialog.getByRole('button', { name: 'Create contact', exact: true }).click()
    await expect(dialog.getByRole('alert')).toContainText('Synthetic address conflict')
    await expect(dialog.getByLabel('Display name', { exact: true })).toHaveValue('External correspondent')
    await dialog.getByLabel('Email address', { exact: true }).fill('another@example.org')
    await dialog.getByRole('button', { name: 'Create contact', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(writes[1]).toEqual({ agent_id: 7, display_name: 'External correspondent', email: 'another@example.org' })
    await expect(page.getByText('External correspondent', { exact: true })).toBeVisible()
    await page.getByText('External correspondent', { exact: true }).click()
    await expect(dialog.getByText('another@example.org', { exact: true })).toBeVisible()
  })
}

test('editing follows privileges and cancellation discards staged splitting', async ({ page }) => {
  await fixtures(page)
  await mount(page, component, { privileges: ['CONTACT_ACCESS'] })
  await page.getByText('Synthetic contact', { exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Add email contact', exact: true })).toHaveCount(0)
  await setPrivileges(page, ['CONTACT_EDIT', 'MEMORY_EDIT'])
  await expect(page.getByText('Synthetic contact', { exact: true })).toBeVisible()
  await page.getByRole('checkbox').last().check()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('checkbox').last().uncheck()
  await page.getByText('Synthetic contact', { exact: true }).click()
  await page.getByLabel('Display name', { exact: true }).fill('Unsaved draft')
  await page.getByRole('button', { name: 'Split identity 2', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click()
  await page.getByRole('button', { name: 'Forget contact Synthetic contact', exact: true }).click()
  await expect(page.getByRole('dialog').getByText('Permanently forget contact', { exact: true })).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await page.getByRole('button', { name: 'Edit contact Synthetic contact', exact: true }).click()
  await expect(page.getByLabel('Display name', { exact: true })).toHaveValue('Synthetic contact')
  await expect(page.getByRole('button', { name: 'Split identity 2', exact: true })).toBeEnabled()
  await setPrivileges(page, ['CONTACT_ACCESS'])
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await setPrivileges(page, [])
  await expect(page.getByText('Synthetic contact', { exact: true })).toHaveCount(0)
  await setPrivileges(page, ['CONTACT_ACCESS'])
  await expect(page.getByText('Synthetic contact', { exact: true })).toBeVisible()
})

for (const creating of [false, true]) {
  test(`a late ${creating ? 'creation' : 'save'} cannot restore the previous agent's contact`, async ({ page }) => {
    await fixtures(page)
    let finish
    const pending = new Promise(resolve => { finish = resolve })
    await page.route(creating ? '**/api/contacts' : `**/api/contacts/${initial.memory_item_id}`, async route => {
      await pending
      await route.fulfill({ status: creating ? 201 : 200, json: { ...initial, display_name: 'Edited contact' } })
    })
    await mount(page, component, { privileges: ['CONTACT_EDIT'] })
    await page.getByRole('button', { name: creating ? 'Add email contact' : 'Edit contact Synthetic contact', exact: true }).click()
    await page.getByLabel('Display name', { exact: true }).fill('Edited contact')
    if (creating) await page.getByLabel('Email address', { exact: true }).fill('outside@example.org')
    const method = creating ? 'POST' : 'PATCH'
    const request = page.waitForRequest(request => request.method() === method)
    await page.getByRole('dialog').getByRole('button', { name: creating ? 'Create contact' : 'Save', exact: true }).click()
    await request
    await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click()
    await page.getByRole('combobox', { name: 'Agent', exact: true }).click()
    await page.getByRole('option', { name: 'Bob Example', exact: true }).click()
    const response = page.waitForResponse(response => response.request().method() === method)
    finish()
    await response
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Edit contact Synthetic contact', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Edit contact Edited contact', exact: true })).toHaveCount(0)
  })
}
