import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const catalogue = {
  teams: [{id:10,name:'Sales',description:'',order:0},{id:20,name:'Direction',description:'',order:1}],
  agents: [{id:1,label:'Atlas',code:'atlas',manager_user_id:9,team_ids:[10]},{id:2,label:'Ada',code:'ada',manager_user_id:9,team_ids:[20]}],
}

const avatarSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48"><rect width="48" height="48" rx="24" fill="#EBF5FE"/><circle cx="24" cy="18" r="8" fill="#087FF5"/><path d="M8 44a16 16 0 0 1 32 0" fill="#087FF5"/></svg>'
const imageData = Buffer.from(avatarSvg).toString('base64')
const people = [
  { id: 7, label: 'Sophie', active: true, avatar_url: `data:image/svg+xml;base64,${imageData}` },
  { id: 8, label: 'Nicolas', active: true, avatar_url: `data:image/svg+xml;base64,${imageData}` },
]

async function teamFixtures(page, { failFirstAgentSave = false, many = false } = {}) {
  const writes = []
  const teams = catalogue.teams.map(team => ({ ...team }))
  const agents = catalogue.agents.map(agent => ({ ...agent, team_ids: [...agent.team_ids], has_avatar: true }))
  if (many) for (let i = 3; i <= 20; i++) agents.push({ id: i, label: `Worker ${i}`, team_ids: [20], has_avatar: false })
  await page.route('**/api/agents/selection?scope=teams', route => route.fulfill({ json: agents.map(({ id, label, has_avatar }) => ({ id, label, has_avatar })) }))
  const humanTeams = new Map([[10, [7]], [20, []]])
  let failAgent = failFirstAgentSave
  const fullTeam = team => {
    const members = people.filter(person => humanTeams.get(team.id)?.includes(person.id))
    return { ...team, human_count: members.length, human_members: members }
  }
  await page.route('**/api/agents/*/avatar', route => route.fulfill({ contentType: 'image/svg+xml', body: avatarSvg }))
  await page.route('**/api/agents/teams/agents', route => route.fulfill({ json: agents }))
  await page.route('**/api/teams', async route => {
    if (route.request().method() === 'POST') {
      const team = { id: 30, order: teams.length, ...route.request().postDataJSON() }
      teams.push(team)
      humanTeams.set(team.id, [])
      writes.push(['create', team.id])
      await route.fulfill({ status: 201, json: fullTeam(team) })
    } else await route.fulfill({ json: teams.map(fullTeam) })
  })
  await page.route('**/api/teams/humans?*', route => route.fulfill({ json: people }))
  await page.route(/\/api\/teams\/\d+\/position$/, async route => {
    const id = Number(route.request().url().split('/').at(-2))
    const { target_team_id: target, after } = route.request().postDataJSON()
    const [team] = teams.splice(teams.findIndex(item => item.id === id), 1)
    teams.splice(teams.findIndex(item => item.id === target) + Number(after), 0, team)
    teams.forEach((item, index) => { item.order = index })
    writes.push(['move', id, target, after])
    await route.fulfill({ status: 204 })
  })
  await page.route(/\/api\/teams\/\d+$/, async route => {
    const id = Number(route.request().url().split('/').at(-1))
    expect(route.request().postDataJSON()).not.toHaveProperty('order')
    Object.assign(teams.find(team => team.id === id), route.request().postDataJSON())
    writes.push(['edit', id])
    await route.fulfill({ json: fullTeam(teams.find(team => team.id === id)) })
  })
  await page.route(/\/api\/teams\/\d+\/humans$/, route => {
    const id = Number(route.request().url().split('/').at(-2))
    return route.fulfill({ json: people.filter(person => humanTeams.get(id)?.includes(person.id)) })
  })
  await page.route(/\/api\/teams\/\d+\/humans\/\d+$/, async route => {
    const parts = route.request().url().split('/')
    const teamId = Number(parts.at(-3)), id = Number(parts.at(-1))
    const { present } = route.request().postDataJSON()
    writes.push(['human', teamId, id, present])
    humanTeams.set(teamId, present ? [...humanTeams.get(teamId), id] : humanTeams.get(teamId).filter(value => value !== id))
    await route.fulfill({ status: 204 })
  })
  await page.route('**/api/agents/teams/*/members/*', async route => {
    const parts = route.request().url().split('/')
    const teamId = Number(parts.at(-3)), id = Number(parts.at(-1))
    if (failAgent) { failAgent = false; await route.fulfill({ status: 503 }); return }
    const { present } = route.request().postDataJSON()
    const agent = agents.find(value => value.id === id)
    agent.team_ids = present ? [...agent.team_ids, teamId] : agent.team_ids.filter(value => value !== teamId)
    writes.push(['agent', teamId, id, present])
    await route.fulfill({ status: 204 })
  })
  return writes
}

async function addMember(page, kind, name) {
  const section = page.getByRole('region', { name: kind, exact: true })
  await section.getByRole('combobox').click()
  const option = page.getByRole('option', { name, exact: true })
  await expect(option.getByRole('img', { name })).toBeVisible()
  await option.click()
  await section.getByRole('button', { name: 'Add', exact: true }).click()
}

test('team list shows members with avatars and readers can inspect the dialog without editing', async ({ page }) => {
  await teamFixtures(page, { many: true })
  await mount(page, 'core/team/components/TeamManager.vue', { privileges: ['TEAM_ACCESS'] })
  const sales = page.getByRole('row').filter({ has: page.getByRole('button', { name: 'Sales', exact: true }) })
  await expect(sales.getByRole('img', { name: 'Sophie', exact: true })).toBeVisible()
  await expect(sales.getByRole('img', { name: 'Atlas', exact: true })).toBeVisible()
  const direction = page.getByRole('row').filter({ has: page.getByRole('button', { name: 'Direction', exact: true }) })
  await expect(direction).toContainText('19')
  await expect(direction).not.toContainText('Worker')
  await sales.getByRole('button', { name: 'Sales', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('Sophie', { exact: true })).toBeVisible()
  await expect(dialog.getByText('Atlas', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('button', { name: /^Remove/ })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'New team' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /^Move / })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
})

for (const viewport of [{ width: 1400, height: 1000 }, { width: 390, height: 850 }]) {
  test(`team editing stages both types of members until save and preserves cancellation at ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    const writes = await teamFixtures(page)
    await mount(page, 'core/team/components/TeamManager.vue', { privileges: ['TEAM_ACCESS', 'TEAM_EDIT', 'TEAM_MEMBERS_EDIT'] })
    await page.getByRole('button', { name: 'Sales', exact: true }).click()
    await addMember(page, 'Humans', 'Nicolas')
    await addMember(page, 'AI agents', 'Ada')
    expect(writes).toEqual([])
    await page.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    expect(writes).toEqual([])
    await page.getByRole('button', { name: 'Sales', exact: true }).click()
    await expect(page.getByRole('dialog').getByText('Nicolas', { exact: true })).toHaveCount(0)
    await addMember(page, 'Humans', 'Nicolas')
    await addMember(page, 'AI agents', 'Ada')
    await page.getByRole('button', { name: 'Remove Sophie from team', exact: true }).click()
    await page.getByRole('button', { name: 'Remove Atlas from team', exact: true }).click()
    await page.getByRole('dialog').getByLabel('Name', { exact: true }).fill('Marketing')
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect.poll(() => writes).toEqual([
      ['edit', 10], ['human', 10, 7, false], ['human', 10, 8, true], ['agent', 10, 1, false], ['agent', 10, 2, true],
    ])
    await page.getByRole('button', { name: 'Marketing', exact: true }).click()
    await expect(page.getByRole('dialog').getByRole('img', { name: 'Nicolas', exact: true })).toBeVisible()
    await expect(page.getByRole('dialog').getByRole('img', { name: 'Ada', exact: true })).toBeVisible()
    await page.screenshot({ path: `/artifacts/team-editor-${viewport.width}.png`, fullPage: true, animations: 'disabled' })
    await page.evaluate(() => window.testApp.dark(true))
    await page.screenshot({ path: `/artifacts/team-editor-dark-${viewport.width}.png`, fullPage: true, animations: 'disabled' })
  })
}

test('new team retries a failed membership save without recreating the team or losing its draft', async ({ page }) => {
  const writes = await teamFixtures(page, { failFirstAgentSave: true })
  await mount(page, 'core/team/components/TeamManager.vue', { privileges: ['TEAM_ACCESS', 'TEAM_EDIT', 'TEAM_MEMBERS_EDIT'] })
  await page.getByRole('button', { name: 'New team' }).click()
  await page.getByRole('dialog').getByLabel('Name', { exact: true }).fill('Support')
  await addMember(page, 'Humans', 'Nicolas')
  await addMember(page, 'AI agents', 'Ada')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Could not save all changes')
  await expect(page.getByRole('dialog').getByText('Ada', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(writes.filter(write => write[0] === 'create')).toEqual([['create', 30]])
  expect(writes.filter(write => write[0] === 'human')).toEqual([['human', 30, 8, true]])
  expect(writes.at(-1)).toEqual(['agent', 30, 2, true])
})

test('dragging a team persists its position and later editing preserves the order', async ({ page }) => {
  const writes = await teamFixtures(page)
  await mount(page, 'core/team/components/TeamManager.vue', { privileges: ['TEAM_ACCESS', 'TEAM_EDIT'] })
  const rows = page.locator('tbody tr')
  await page.getByRole('button', { name: 'Move Direction', exact: true }).dragTo(
    rows.filter({ hasText: 'Sales' }), { targetPosition: { x: 60, y: 2 } },
  )
  await expect.poll(() => writes.filter(write => write[0] === 'move')).toEqual([['move', 20, 10, false]])
  await expect(rows.first()).toContainText('Direction')
  await page.getByRole('button', { name: 'Direction', exact: true }).click()
  await page.getByRole('dialog').getByLabel('Name', { exact: true }).fill('Leadership')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(rows.first()).toContainText('Leadership')
  await page.getByRole('button', { name: 'Move Leadership', exact: true }).press('ArrowDown')
  await expect.poll(() => writes.at(-1)).toEqual(['move', 20, 10, true])
  await expect(rows.first()).toContainText('Sales')
})

test('touch dragging moves teams in the mobile list', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 850 })
  const writes = await teamFixtures(page)
  await mount(page, 'core/team/components/TeamManager.vue', { privileges: ['TEAM_ACCESS', 'TEAM_EDIT'] })
  const source = await page.getByRole('button', { name: 'Move Direction', exact: true }).boundingBox()
  const target = await page.locator('[data-team-id="10"]').boundingBox()
  expect(source).not.toBeNull()
  expect(target).not.toBeNull()
  const session = await page.context().newCDPSession(page)
  const x = source.x + source.width / 2, y = source.y + source.height / 2
  await session.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] })
  await session.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: target.x + 30, y: target.y + 8 }] })
  await session.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
  await expect.poll(() => writes.filter(write => write[0] === 'move')).toEqual([['move', 20, 10, false]])
  await expect(page.locator('[data-team-id]').first()).toHaveAttribute('data-team-id', '20')
})
