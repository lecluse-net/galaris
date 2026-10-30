import { test, expect, mount, jsonRoute } from './fixtures.mjs'

for (const width of [1440, 390]) test(`file browsing opens generic and personal skills in a modal at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  await page.route('**/api/file-share/browser/thumbnail?*', route => route.fulfill({ status: 404 }))
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [
    { scheme: 'galaris', label: 'Galaris', capabilities: ['info', 'list'], native: true },
  ])
  const generic = { uri: 'galaris://skill/sample/', name: 'Synthetic guide', is_collection: true, capabilities: ['info', 'list'], metadata: { code: 'sample' } }
  const personal = { ...generic, uri: 'galaris://skill/personnal/7/private-guide/', name: 'Synthetic personal guide' }
  const personalBranch = { ...generic, uri: 'galaris://skill/personnal/', name: 'Personal skills' }
  const owner = { ...generic, uri: 'galaris://skill/personnal/7/', name: 'Alice Example' }
  const library = { ...generic, uri: 'galaris://skill/', name: 'Skills' }
  const category = { ...generic, uri: 'galaris://skill/_category-11/', name: 'Synthetic procedures' }
  const uncategorized = { ...generic, uri: 'galaris://skill/_uncategorized/', name: 'Uncategorized' }
  const loose = { ...generic, uri: 'galaris://skill/loose-guide/', name: 'Synthetic loose guide' }
  const files = skill => ['SKILL.md', 'references/notes.md'].map(path => ({
    uri: skill.uri + path, name: path.split('/').at(-1), is_collection: false,
    media_type: 'text/markdown', size: 80, capabilities: ['info', 'read'], metadata: { path },
  }))
  const reads = []
  await page.route('**/api/file-share/browser/entries?*', route => {
    const params = new URL(route.request().url()).searchParams
    expect(params.get('agent_id')).toBe('7')
    const uri = params.get('uri')
    reads.push(uri)
    const entries = uri === generic.uri ? files(generic) : uri === personal.uri ? files(personal) : uri === loose.uri ? files(loose)
      : uri === personalBranch.uri ? [owner] : uri === owner.uri ? [personal]
      : uri === category.uri ? [generic] : uri === uncategorized.uri ? [loose]
      : uri === library.uri ? [category, uncategorized, personalBranch] : [library]
    const ancestors = uri === owner.uri ? [
      { uri: 'galaris://', name: 'Galaris' }, { uri: 'galaris://skill/', name: 'Skills' }, personalBranch, owner,
    ] : [category.uri, uncategorized.uri].includes(uri) ? [
      { uri: 'galaris://', name: 'Galaris' }, library, uri === category.uri ? category : uncategorized,
    ] : []
    return route.fulfill({ json: { uri, entries, ancestors, truncated: false, next_cursor: null } })
  })
  let failRead = true
  await page.route('**/api/file-share/browser/content?*', route => {
    const params = new URL(route.request().url()).searchParams
    expect(params.get('agent_id')).toBe('7')
    if (failRead) return route.fulfill({ status: 403, json: { detail: 'Synthetic access refusal' } })
    return route.fulfill({ contentType: 'text/markdown', body: params.get('uri').endsWith('SKILL.md') ? '# Synthetic instructions' : '# Synthetic reference' })
  })
  await mount(page, 'app/file_share/components/AgentFileBrowser.vue', {
    props: { agentId: 7, initialUri: 'galaris://skill/' }, privileges: ['FILE_ACCESS'],
    containerStyle: { height: '100vh', display: 'flex' }, dark: width === 390,
  })
  const main = page.getByRole('main')
  await main.getByRole('button', { name: `Open ${category.name}`, exact: true }).click()
  await expect(main.getByRole('navigation').getByRole('button', { name: category.name, exact: true })).toBeVisible()
  await expect(main.getByRole('button', { name: `Open ${generic.name}`, exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('skill-icons.png'), fullPage: true })
  await main.getByRole('button', { name: `Open ${generic.name}`, exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('alert')).toBeVisible()
  failRead = false
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(dialog.getByText('Synthetic instructions', { exact: true })).toBeVisible()
  await dialog.getByText('notes.md', { exact: true }).click()
  await expect(dialog.getByText('Synthetic reference', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('skill-modal.png'), fullPage: true })
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await main.getByRole('button', { name: `Open ${generic.name}`, exact: true }).press('Enter')
  await expect(dialog.getByText('Synthetic instructions', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await main.getByRole('navigation').getByRole('button', { name: 'Skills', exact: true }).click()
  await main.getByRole('button', { name: 'Open Uncategorized', exact: true }).click()
  await main.getByRole('button', { name: `Open ${loose.name}`, exact: true }).click()
  await expect(dialog.getByText('Synthetic instructions', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await main.getByRole('navigation').getByRole('button', { name: 'Skills', exact: true }).click()
  await main.getByRole('button', { name: 'Open Personal skills', exact: true }).click()
  await main.getByRole('button', { name: 'Open Alice Example', exact: true }).click()
  await expect(main.getByRole('navigation').getByRole('button', { name: 'Alice Example', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('personal-skill-owner.png'), fullPage: true })
  await main.getByRole('button', { name: `Open ${personal.name}`, exact: true }).click()
  await expect(dialog.getByText('Synthetic instructions', { exact: true })).toBeVisible()
  await expect(dialog).toContainText(personal.name)
  await page.keyboard.press('Escape')
  await expect.poll(() => reads.includes(personalBranch.uri)).toBe(true)
  await expect(dialog).toHaveCount(0)
  // Selecting attachments continues to browse package files instead of opening a skill modal.
  await main.getByRole('navigation').getByRole('button', { name: 'Skills', exact: true }).click()
  await page.evaluate(() => window.testApp.setProps({ selection: true }))
  await main.getByRole('button', { name: `Open ${category.name}`, exact: true }).click()
  await main.getByRole('button', { name: `Open ${generic.name}`, exact: true }).click()
  await expect(main.getByRole('button', { name: 'Select SKILL.md', exact: true })).toBeVisible()
  await expect(dialog).toHaveCount(0)
})
