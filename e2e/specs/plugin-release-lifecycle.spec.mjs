import { test, expect } from '@playwright/test'

test('a broken signed update preserves the browser editor and its saved bytes', async ({ page, request }) => {
  const seed = await request.post('/api/__test/seed')
  expect(seed.ok(), await seed.text()).toBeTruthy()
  const owner = await seed.json()
  const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('/user/login')
  await refresh
  await page.locator('input[type=email]').fill(owner.email)
  await page.locator('input[type=password]').fill(owner.password)
  const authenticated = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const { access_token: token } = await (await authenticated).json()
  const headers = { Authorization: `Bearer ${token}`, 'X-Editorial-Profile-Version': '1' }
  const account = await request.get('/api/auth/me', { headers })
  expect(account.ok(), await account.text()).toBeTruthy()
  const { id: userId } = await account.json()

  async function install(version) {
    const archive = await request.get(`/api/__test/plugin-archives/${version}`)
    expect(archive.ok(), await archive.text()).toBeTruthy()
    const file = { name: `qualification-${version}.zip`, mimeType: 'application/zip', buffer: await archive.body() }
    const preview = await request.post('/api/plugins/preview', { headers, multipart: { file } })
    expect(preview.ok(), await preview.text()).toBeTruthy()
    const { digest, host_identity } = await preview.json()
    if (version === '1.0.0') expect(digest).toBe('bf6ff313c02ae50fc26d7956ab8e6c5404062b0f48540c66f015977a8ebfd516')
    const stored = await request.post('/api/plugins/install', { headers, multipart: { file, digest, host_identity } })
    expect(stored.ok(), await stored.text()).toBeTruthy()
    expect((await stored.json()).active).toBe(false)
    return host_identity
  }

  const code = 'fixture.revision-editor'
  const original = await install('1.0.0')
  await page.goto('/plugin')
  const card = page.getByRole('article', { name: /Éditeur de qualification|Qualification editor/ })
  const activation = card.getByRole('switch')
  await expect(activation).toHaveAttribute('aria-checked', 'false')
  await activation.click()
  await expect(activation).toHaveAttribute('aria-checked', 'true')
  const created = await request.post('/api/documents', { headers, data: {
    owner_kind: 'user', owner_id: userId, title: 'Synthetic release document', document_format: code,
  } })
  expect(created.ok(), await created.text()).toBeTruthy()
  const { id } = await created.json()
  const document = `/api/documents/${id}`
  const edited = await request.patch(document, { headers, data: { expected_revision: 1,
    payload: { base64: Buffer.from('Content saved before update').toString('base64') } } })
  expect(edited.ok(), await edited.text()).toBeTruthy()
  await page.goto(`/documents?document_id=${id}`)
  await expect(page.getByText('Content saved before update', { exact: true })).toBeVisible()

  const update = await install('2.0.0')
  const failure = await request.post(`/api/plugins/${code}/2.0.0/activate`, {
    headers, data: { host_identity: update },
  })
  expect(failure.status()).toBe(409)
  expect(await failure.json()).toEqual({ detail: 'activation_error' })
  await page.reload()
  await expect(page.getByText('Content saved before update', { exact: true })).toBeVisible()
  const selected = await request.get(`/api/plugins/${code}`, { headers })
  expect((await selected.json()).releases.filter(release => release.active).map(release => release.manifest.version)).toEqual(['1.0.0'])

  for (const operation of ['deactivate', 'remove']) {
    const result = await request.post(`/api/plugins/${code}/1.0.0/${operation}`, {
      headers, data: { host_identity: original },
    })
    expect(result.ok(), await result.text()).toBeTruthy()
  }
  expect(await (await request.get(`${document}/source`, { headers })).text()).toBe('Content saved before update')
  expect(await (await request.get(`${document}/source?revision=1`, { headers })).text()).toBe('Original qualification content')
  await install('1.0.0')
  await page.goto('/plugin')
  // The most recent installed release appears first. The card exposes other versions in history.
  await card.getByRole('button', { name: /Versions et historique|Releases and history/i }).click()
  await card.getByRole('combobox', { name: 'Version', exact: true }).click()
  await page.getByRole('option', { name: /1\.0\.0/ }).click()
  await activation.click()
  await expect(activation).toHaveAttribute('aria-checked', 'true')
  await page.goto(`/documents?document_id=${id}`)
  await expect(page.getByText('Content saved before update', { exact: true })).toBeVisible()
})
