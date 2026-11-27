import { test, expect, jsonRoute, mount } from './fixtures.mjs'

for (const width of [1440, 390]) {
  test(`shows limited sidebar gauges and sends a credit request (${width}px)`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    const account = {
      user_id: 1, label: 'Synthetic account', requests: [],
      envelopes: [
        { period: 'session', limit: '10', spent: '8', granted: '0', starts_at: '2026-11-27T07:00:00Z', resets_at: '2026-11-27T12:00:00Z', exhausted: false },
        { period: 'weekly', limit: '20', spent: '19', granted: '0', starts_at: '2026-11-23T00:00:00Z', resets_at: '2026-11-30T00:00:00Z', exhausted: false },
        { period: 'monthly', limit: null, spent: '19', granted: '0', starts_at: '2026-11-01T00:00:00Z', resets_at: '2026-12-01T00:00:00Z', exhausted: false },
      ],
    }
    await page.route('**/api/llm-budget/me', route => route.fulfill({ json: { account, can_request_credit: true, can_configure_own: false } }))
    await jsonRoute(page, '**/api/llm-budget/managed?*', {
      items: [
        { ...account, user_id: 3, label: 'Managed test account', can_configure: false, can_manage_credits: true },
        { ...account, user_id: 4, label: 'Other test account', can_configure: false, can_manage_credits: true },
      ],
      total: 2,
    })
    await page.route('**/api/llm-budget/requests', route => {
      const input = route.request().postDataJSON()
      expect(input).toEqual({ period: 'session', amount: '2.50' })
      account.requests = [{ ...input, id: 'request', status: 'pending' }]
      return route.fulfill({ status: 201, json: account.requests[0] })
    })
    const desktop = width >= 1024
    await mount(page, 'app/llm/pages/usage.vue', { route: '/llm/usage', shell: true, dark: !desktop, locale: desktop ? 'fr' : 'en' })
    if (desktop) {
      await expect(page.getByRole('link', { name: /^5 heures · 8,00\s+\$ sur 10,00\s+\$ ·/ })).toHaveAttribute('href', '/llm/usage')
      await expect(page.getByRole('link', { name: /^Mensuelle ·/ })).toHaveCount(0)
    } else {
      await page.locator('.q-drawer__backdrop').click({ position: { x: width - 10, y: 200 } })
    }
    await expect(page.getByRole('heading', { name: desktop ? 'Mes limites d’utilisation' : 'My usage limits' })).toBeVisible()
    const table = page.getByRole('table')
    await expect(table.getByRole('columnheader')).toHaveText(desktop
      ? ['Utilisateur', '5 heures', 'Hebdomadaire', 'Mensuelle', 'Actions']
      : ['User', '5 hours', 'Weekly', 'Monthly', 'Actions'])
    await expect(table.getByRole('cell').nth(2)).toBeEmpty()
    await expect(table.getByRole('rowheader')).toHaveText(['Managed test account', 'Other test account'])
    await expect(page.getByRole('button', { name: desktop ? 'Modifier mes plafonds' : 'Change my limits' })).toHaveCount(0)
    const dialog = page.getByRole('dialog')
    await table.getByRole('rowheader').first().click()
    await expect(dialog).toHaveCount(0)
    await page.screenshot({ animations: 'disabled', path: testInfo.outputPath('inference-usage.png') })
    await page.getByRole('button', { name: desktop ? 'Demander des crédits' : 'Request credits' }).click()
    await dialog.getByLabel(desktop ? 'Montant ($)' : 'Amount ($)').fill('2.50')
    await dialog.getByRole('button', { name: desktop ? 'Valider' : 'Confirm' }).click()
    await expect(dialog).toHaveCount(0)
    await page.getByRole('button', { name: desktop ? 'Demandes de crédits' : 'Credit requests' }).click()
    await expect(page.getByText(desktop ? '5 heures · 2,50 $ · En attente' : '5 hours · $2.50 · Pending', { exact: true })).toBeVisible()
  })
}

test('a user with the own-budget privilege can set and clear a limit', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const account = {
    user_id: 1, label: 'Synthetic account', requests: [],
    envelopes: ['session', 'weekly', 'monthly'].map(period => ({
      period, limit: period === 'weekly' ? '7.125' : null, spent: '0', granted: '0', resets_at: null, exhausted: false,
    })),
  }
  await page.route('**/api/llm-budget/me', route => route.fulfill({
    json: { account, can_request_credit: false, can_configure_own: true },
  }))
  await jsonRoute(page, '**/api/llm-budget/managed?*', { items: [], total: 0 })
  await page.route('**/api/llm-budget/policies/1', route => {
    const input = route.request().postDataJSON()
    expect(input).toEqual({ session_limit: null, weekly_limit: '7.125', monthly_limit: input.monthly_limit })
    expect(['5.25', null]).toContain(input.monthly_limit)
    account.envelopes[2].limit = input.monthly_limit
    return route.fulfill({ status: 204 })
  })
  await mount(page, 'app/llm/pages/usage.vue', { route: '/llm/usage', dark: true })
  await expect(page.getByRole('progressbar')).toHaveCount(1)
  await expect(page.getByRole('table')).toHaveCount(0)
  for (const limit of ['5.25', '']) {
    await page.getByRole('button', { name: 'Change my limits' }).click()
    const dialog = page.getByRole('dialog', { name: 'Change limits' })
    await expect(dialog.getByLabel('Budget manager')).toHaveCount(0)
    await expect(dialog.locator('input[type="password"]')).toHaveCount(0)
    await expect(dialog.getByRole('spinbutton')).toHaveCount(3)
    await expect(dialog.getByLabel('Weekly', { exact: true })).toHaveValue('7.13')
    const monthly = dialog.getByLabel('Monthly', { exact: true })
    if (limit) {
      await monthly.fill('5.251')
      await dialog.getByRole('button', { name: 'Confirm' }).click()
      await expect(dialog).toBeVisible()
      await monthly.fill(limit)
      await monthly.press('ArrowUp')
      await expect(monthly).toHaveValue('6.25')
      await dialog.getByRole('button', { name: 'Decrease the Monthly limit by $1' }).click()
      await expect(monthly).toHaveValue(limit)
      await page.screenshot({ animations: 'disabled', path: testInfo.outputPath('limits-dialog-mobile.png') })
    } else {
      await monthly.fill('')
    }
    await dialog.getByRole('button', { name: 'Confirm' }).click()
    await expect(dialog).toHaveCount(0)
    await expect(page.getByRole('progressbar')).toHaveCount(limit ? 2 : 1)
    if (limit) await expect(page.getByText('$0.00 of $5.25', { exact: true })).toBeVisible()
  }
})

test('an administrator can open their own settings and the settings of another user', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const account = {
    user_id: 1, label: 'Synthetic administrator', requests: [],
    envelopes: ['session', 'weekly', 'monthly'].map(period => ({
      period, limit: null, spent: '0', granted: '0', resets_at: null, exhausted: false,
    })),
  }
  await jsonRoute(page, '**/api/llm-budget/me', { account, can_request_credit: false, can_configure_own: true })
  await page.route('**/api/llm-budget/managed?*', route => {
    const params = new URL(route.request().url()).searchParams
    expect(params.get('page_size')).toBe('50')
    const secondPage = params.get('page') === '2'
    const items = [{
      ...account,
      user_id: secondPage ? 3 : 2,
      label: secondPage ? 'Second page account' : 'Other test account',
      can_configure: true, can_manage_credits: false,
    }]
    return route.fulfill({ json: { items, total: 51 } })
  })
  await mount(page, 'app/llm/pages/usage.vue', { route: '/llm/usage', shell: true, locale: 'fr' })
  await page.getByRole('button', { name: 'Modifier mes plafonds', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText(account.label)).toBeVisible()
  await dialog.getByRole('button', { name: 'Annuler' }).click()
  const table = page.getByRole('table')
  await expect(table.getByRole('rowheader')).toHaveCount(1)
  await expect(table.getByRole('rowheader')).toContainText('Other test account')
  for (const cell of (await table.getByRole('cell').all()).slice(0, 3)) await expect(cell).toBeEmpty()
  await table.getByRole('rowheader').click()
  await expect(dialog.getByText('Other test account')).toBeVisible()
  await dialog.getByLabel('5 heures', { exact: true }).click()
  await page.screenshot({ animations: 'disabled', path: testInfo.outputPath('limits-dialog-desktop.png') })
  await dialog.getByRole('button', { name: 'Annuler' }).click()
  await table.getByRole('cell').last().getByRole('button', { name: 'Modifier les plafonds' }).press('Enter')
  await expect(dialog.getByText('Other test account')).toBeVisible()
  await dialog.getByRole('button', { name: 'Annuler' }).click()
  await page.getByRole('button', { name: /^(page suivante|next page)$/i }).click()
  await expect(table.getByRole('rowheader')).toHaveText('Second page account')
})

test('a team lead can configure members and grant credit only for active windows', async ({ page }) => {
  const account = { user_id: 1, label: 'Synthetic manager', envelopes: [], requests: [] }
  const target = {
    user_id: 2, label: 'Managed test account', can_configure: true, can_manage_credits: true,
    envelopes: [
      { period: 'monthly', limit: '5', granted: '0', spent: '0', starts_at: '2026-11-01T00:00:00Z', resets_at: '2026-12-01T00:00:00Z' },
      { period: 'session', limit: '1', granted: '0', spent: '0', starts_at: null, resets_at: null },
    ],
    requests: [
      { id: 'request', period: 'monthly', amount: '2', status: 'pending' },
      { id: 'inactive-request', period: 'session', amount: '2', status: 'pending' },
    ],
  }
  await jsonRoute(page, '**/api/llm-budget/me', { account, can_request_credit: false, can_configure_own: false })
  await page.route('**/api/llm-budget/managed?*', route => route.fulfill({ json: { items: [target], total: 1 } }))
  await page.route('**/api/llm-budget/requests/request/review', route => {
    expect(route.request().postDataJSON()).toEqual({ decision: 'approved' })
    target.requests = target.requests.filter(request => request.id !== 'request')
    target.envelopes[0].granted = '2'
    return route.fulfill({ status: 204 })
  })
  await mount(page, 'app/llm/pages/usage.vue', { route: '/llm/usage' })
  const dialog = page.getByRole('dialog')
  await page.getByRole('rowheader', { name: target.label }).click()
  await expect(dialog.getByRole('spinbutton')).toHaveCount(3)
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await page.getByRole('button', { name: 'Add credit' }).click()
  await dialog.getByRole('combobox', { name: 'Usage limit' }).click()
  await expect(page.getByRole('option')).toHaveText(['Monthly'])
  await page.getByRole('option', { name: 'Monthly' }).click()
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await page.getByRole('button', { name: 'Credit requests' }).click()
  await page.getByRole('button', { name: 'Grant', exact: true }).click()
  await expect(page.getByText('$0.00 of $7.00', { exact: true })).toBeVisible()
  await expect(dialog).toHaveCount(0)
  await page.getByRole('button', { name: 'Credit requests' }).click()
  await expect(page.getByText('5 hours · $2.00 · Pending', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Grant', exact: true })).toHaveCount(0)
})
