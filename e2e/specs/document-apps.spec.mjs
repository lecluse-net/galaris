import { test, expect } from '@playwright/test'

test('two document applications collect into the same Dataset with isolated JavaScript', async ({ page, request }, testInfo) => {
  const fixture = await (await request.post('/api/__test/seed')).json()
  const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('/user/login'); await refresh
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const authentication = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await authentication).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}`, 'X-Editorial-Profile-Version': '1' }
  const datasetResponse = await request.post('/api/memory/items', { headers, data: {
    owner_agent_id: fixture.agent_id, title: 'Synthetic responses', node_kind: 'document', memory_type: 'working',
    document_type: 'dataset', media_type: 'application/json', payload: { text: '[]' },
  } })
  expect(datasetResponse.ok(), await datasetResponse.text()).toBeTruthy()
  const dataset = await datasetResponse.json()
  const definition = {
    id: 'form', title: 'Response form', datasets: { entries: { uri: `document://${dataset.id}`, access: 'write' } },
    html: '<form><label>Answer <input name="answer" required></label><button>Submit</button></form><p id="result" role="status"></p><button id="navigate">Navigate</button>',
    javascript: `
      document.querySelector('form').onsubmit = async event => {
        event.preventDefault(); const button = document.querySelector('form button'); button.disabled = true;
        try {
          const current = await galaris.datasets.read('entries');
          const next = await galaris.datasets.append('entries', {answer: new FormData(event.target).get('answer')}, current.revision);
          document.getElementById('result').textContent = 'Saved ' + next.data.length;
        } catch(error) { document.getElementById('result').textContent = error.message; }
        finally { button.disabled = false; }
      };
      try { top.document.body.dataset.escaped = 'yes'; } catch {}
      document.getElementById('navigate').onclick = () => { location.href = 'https://leak.example.test/exfiltrate'; };`,
  }
  const html = '<h2>Data collection</h2><pre><code class="language-galaris-app">' + JSON.stringify(definition).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;') + '</code></pre>'
  const documents = []
  for (const title of ['First form', 'Second form']) {
    const response = await request.post('/api/memory/items', { headers, data: {
      owner_agent_id: fixture.agent_id, title, node_kind: 'document', memory_type: 'working',
      media_type: 'text/html', payload: { text: documents.length ? html : '<p>Data collection</p>' },
    } })
    expect(response.ok(), await response.text()).toBeTruthy()
    documents.push(await response.json())
  }
  for (let index = 0; index < documents.length; index++) {
    await page.goto(`/memory/documents?document_id=${documents[index].id}`)
    if (index === 0) {
      await page.getByRole('button', { name: 'Source', exact: true }).click()
      await page.locator('.ck-source-editing-area textarea').fill('<p>Data collection</p>' + definition.html.replace('<form>', `<form data-dataset="document://${dataset.id}">`) + '<script>' + definition.javascript + '</script>')
      await page.getByRole('button', { name: 'Source', exact: true }).click()
    }
    await expect(page.getByRole('button', { name: 'Source', exact: true })).toBeVisible()
    await expect(page.locator('.ck-editor__editable')).not.toContainText('galaris.datasets.append')
    await page.locator('.ck-galaris-editor').evaluate((element, width) => { element.style.width = width + 'px' }, index === 0 ? 320 : 980)
    const app = page.frameLocator('.document-application iframe').frameLocator('iframe')
    // Generated HTML cannot grant its own access, even for the owner of both documents.
    await app.getByRole('textbox').fill('Unapproved')
    await app.getByRole('button', { name: /^(Submit|Save|Enregistrer)$/ }).click()
    await expect(app.getByRole('status')).toContainText(/Authorize|Autorisez/)
    const unchanged = await (await request.get(`/api/memory/items/${dataset.id}?agent_id=${fixture.agent_id}`, { headers })).json()
    expect(unchanged.revision).toBe(index + 1)
    await page.getByRole('button', { name: /^(Application permissions|Permissions des applications)$/ }).click()
    await page.getByRole('combobox', { name: /^(My permission|Mon autorisation)$/ }).click()
    await page.getByRole('option', { name: /^(Read and write|Lecture et écriture)$/ }).click()
    await expect(page.getByRole('combobox', { name: /^(My permission|Mon autorisation)$/ })).toHaveValue(/^(Read and write|Lecture et écriture)$/)
    await page.getByRole('button', { name: /^(Close|Fermer)$/, exact: true }).last().click()
    await app.getByRole('textbox').fill('Response ' + index)
    await app.getByRole('button', { name: /^(Submit|Save|Enregistrer)$/ }).click()
    await expect(app.getByRole('status')).toHaveText('Saved ' + (index + 1))
    expect(await app.locator('body').evaluate(() => {
      try { new RTCPeerConnection(); return false } catch { return true }
    })).toBe(true)
    expect(await app.locator('body').evaluate(() => {
      try { URL.createObjectURL(new Blob(['<script>0</script>'], { type: 'text/html' })); return false } catch { return true }
    })).toBe(true)
    const exported = page.waitForResponse(response => response.url().endsWith(`/documents/${documents[index].id}/export-pdf`))
    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: /^(Export as PDF|Exporter en PDF)$/ }).click()
    const pdf = await exported
    expect(pdf.ok(), await pdf.text()).toBeTruthy()
    const snapshot = pdf.request().postDataJSON().html
    expect(snapshot).toContain('Saved ' + (index + 1))
    expect(snapshot).toContain('Response ' + index)
    expect(snapshot).not.toMatch(/<script|<iframe|onsubmit=/)
    await (await download).saveAs(testInfo.outputPath(`form-${index}.pdf`))
    expect(await page.evaluate(() => document.body.dataset.escaped)).toBeUndefined()
    // A refresh preserves consent, while another document still needs its own grant.
    await page.reload()
    await expect(app.getByRole('textbox')).toBeVisible()
    const grants = await (await request.get(`/api/memory/documents/${documents[index].id}/app-permissions`, { headers })).json()
    expect(grants.grants[0].access).toBe('write')
  }
  const stored = await (await request.get(`/api/memory/items/${dataset.id}?agent_id=${fixture.agent_id}`, { headers })).json()
  expect(stored.document_type).toBe('dataset')
  expect(stored.revision).toBe(3)
  expect(JSON.parse(stored.payload.text)).toEqual([{ answer: 'Response 0' }, { answer: 'Response 1' }])
  const escaped = []
  await page.route('https://leak.example.test/**', route => { escaped.push(route.request().url()); return route.fulfill({ body: 'Unexpected access' }) })
  await page.frameLocator('.document-application iframe').frameLocator('iframe').getByRole('button', { name: 'Navigate' }).click()
  await expect(page.locator('.document-application iframe')).toHaveCount(0)
  expect(escaped).toEqual([])
  await page.goto(`/memory/documents?document_id=${dataset.id}`)
  await expect(page.getByRole('textbox', { name: /^(Content|Contenu)$/ })).toHaveValue(stored.payload.text)
})
