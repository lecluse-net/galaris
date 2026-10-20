import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const graph = () => ({ schema_version: 'galaris.bpmn/v1', input_schema: {}, output_schema: {}, files: {},
  nodes: ['start', 'work', 'end'].map((id, index) => ({ id, kind: id === 'work' ? 'task' : id,
    title: '', config: id === 'work' ? { prompt: 'Prepare an invented result' } : {}, body: null, x: 60 + index * 240, y: 100 })),
  flows: [{ id: 'f1', source: 'start', target: 'work', condition: null }, { id: 'f2', source: 'work', target: 'end', condition: null }] })

for (const kind of ['task', 'human_task']) {
  test(`${kind} can be dragged between compatible actors without changing its type or flows`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1400 })
    const value = graph()
    value.actors = [
      { id: 'executor', name: 'Executor', kind: 'agent', agent_id: 7, user_id: null },
      { id: 'validator', name: 'Validator', kind: 'agent', agent_id: 8, user_id: null },
      { id: 'requester', name: 'Requester', kind: 'human', agent_id: null, user_id: 11 },
      { id: 'reviewer', name: 'Reviewer', kind: 'human', agent_id: null, user_id: 12 },
    ]
    const from = kind === 'task' ? 'executor' : 'requester', to = kind === 'task' ? 'validator' : 'reviewer'
    const incompatible = kind === 'task' ? 'Reviewer' : 'Executor'
    value.nodes[1].kind = kind; value.nodes[1].config.actor = from
    await mount(page, 'app/process/components/BpmnCanvas.vue', { props: { modelValue: value } })
    await page.getByRole('button', { name: 'Zoom out', exact: true }).click()
    const work = page.getByRole('button', { name: kind === 'task' ? 'Task · work' : 'Human task · work', exact: true })
    const lastGraph = () => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value)
    const layout = () => page.locator('.diagram-board').evaluate(board => ({
      laneHeights: [...board.querySelectorAll('.swimlane')].map(lane => lane.offsetHeight),
      positions: [...board.querySelectorAll('[data-process-node]')].map(node => ({ id: node.dataset.processNode, x: node.offsetLeft, y: node.offsetTop })),
    }))
    async function moveTo(name) {
      const source = await work.boundingBox(), lane = await page.locator('.swimlane').filter({ has: page.getByRole('button', { name: `Remove actor ${name}`, exact: true }) }).boundingBox()
      expect(source).toBeTruthy(); expect(lane).toBeTruthy()
      await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2)
      await page.mouse.down()
      await page.mouse.move(source.x + source.width / 2, lane.y + lane.height / 2, { steps: 8 })
    }
    await moveTo(kind === 'task' ? 'Validator' : 'Reviewer')
    expect(await lastGraph()).toBeUndefined() // Assignment changes when dropped, not while hovering.
    await page.mouse.up()
    await expect.poll(async () => (await lastGraph())?.nodes.find(node => node.id === 'work').config.actor).toBe(to)
    const assigned = await lastGraph()
    expect(assigned.nodes.find(node => node.id === 'work')).toMatchObject({ kind, config: { actor: to, prompt: value.nodes[1].config.prompt } })
    expect(assigned.flows).toEqual(value.flows)
    await page.evaluate(() => { window.testApp.events.length = 0 })
    await moveTo(incompatible)
    await page.mouse.up()
    expect(await lastGraph()).toBeUndefined()
    await expect(page.getByRole('status')).toContainText('Choose an actor matching this task’s type.')
    await moveTo(kind === 'task' ? 'Executor' : 'Requester')
    await page.keyboard.press('Escape'); await page.mouse.up()
    expect(await lastGraph()).toBeUndefined()
    await moveTo(kind === 'task' ? 'Executor' : 'Requester')
    await work.dispatchEvent('pointercancel', { pointerId: 1 })
    await page.mouse.up()
    expect(await lastGraph()).toBeUndefined()
    const editingLayout = await layout()
    await moveTo(kind === 'task' ? 'Executor' : 'Requester')
    await page.evaluate(() => window.testApp.setProps({ readonly: true, overlays: { work: '4 s · $0.375' } }))
    await page.mouse.up()
    expect(await lastGraph()).toBeUndefined()
    expect(await layout()).toEqual(editingLayout)
  })
}

test('the diagram connects activities, supports keyboard movement and enforces read-only access', async ({ page }) => {
  const value = graph(); value.flows = []
  await mount(page, 'app/process/components/BpmnCanvas.vue', { props: { modelValue: value } })
  await page.getByRole('button', { name: 'Output of Start', exact: true }).click()
  await page.getByText('Connect to an activity', { exact: true }).click()
  await expect(page.getByRole('menu')).toHaveCount(0)
  await page.getByRole('button', { name: 'Task · work', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value.flows)).toMatchObject([{ source: 'start', target: 'work' }])
  async function dragLink(from, to, cancel = false) {
    const a = await page.getByRole('button', { name: from, exact: true }).boundingBox()
    const b = await page.getByRole('button', { name: to, exact: true }).boundingBox()
    await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2); await page.mouse.down()
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 8 })
    if (cancel) await page.keyboard.press('Escape')
    await page.mouse.up()
  }
  await page.getByRole('button', { name: 'Zoom out', exact: true }).click()
  await dragLink('Output of Task', 'Input of End', true)
  const flows = () => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value.flows)
  expect(await flows()).toHaveLength(1)
  await dragLink('Output of Task', 'Input of End')
  await expect.poll(flows).toHaveLength(2)
  expect(await flows()).toContainEqual(expect.objectContaining({ source: 'work', target: 'end' }))
  await dragLink('Input of End', 'Output of Task')
  expect(await flows()).toHaveLength(2)
  await dragLink('Output of Task', 'Input of Task')
  expect(await flows()).toHaveLength(2)
  await expect(page.getByRole('menu')).toHaveCount(0)
  const work = page.getByRole('button', { name: 'Task · work', exact: true })
  await work.focus(); await page.keyboard.press('ArrowRight')
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value.nodes.find(node => node.id === 'work').x)).toBeGreaterThan(300)
  await page.evaluate(() => { window.testApp.events.length = 0; return window.testApp.setProps({ readonly: true }) })
  await work.focus(); await page.keyboard.press('ArrowRight'); await page.keyboard.press('Delete')
  await expect(page.getByRole('button', { name: 'Output of Start', exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => window.testApp.events.filter(event => ['update:modelValue', 'remove'].includes(event.name)))).toEqual([])
})

for (const readonly of [false, true]) test(`sequence arrows meet ${readonly ? 'element boundaries without handles' : 'visible connection handles'}`, async ({ page }) => {
  const value = graph()
  value.nodes = [
    { ...value.nodes[0], x: 60, y: 100 },
    { ...value.nodes[1], x: 300, y: 100 },
    { ...value.nodes[1], id: 'decision', kind: 'if', x: 600, y: 100, config: { mode: 'code' } },
    { ...value.nodes[1], id: 'parallel', kind: 'parallel', x: 850, y: 100, config: {} },
    { ...value.nodes[2], x: 1120, y: 100 },
  ]
  value.flows = [
    { id: 'start-work', source: 'start', target: 'work', condition: null },
    { id: 'work-decision', source: 'work', target: 'decision', condition: null },
    { id: 'yes', source: 'decision', target: 'parallel', condition: 'decision' },
    { id: 'no', source: 'decision', target: 'end', condition: null },
    { id: 'parallel-end', source: 'parallel', target: 'end', condition: null },
  ]
  await mount(page, 'app/process/components/BpmnCanvas.vue', { props: { modelValue: value, readonly, overlays: { work: '4 s · $0.375' } } })
  await page.getByRole('button', { name: 'Zoom out', exact: true }).click()
  const gaps = await page.locator('.diagram-editor').evaluate((diagram, { flows, readonly }) => {
    return flows.flatMap((flow, index) => {
      const line = diagram.querySelectorAll('.flow-surface .flow-line')[index]
      const length = line.getTotalLength(), matrix = line.getScreenCTM()
      const first = line.getPointAtLength(0), last = line.getPointAtLength(length)
      const before = line.getPointAtLength(Math.max(0, length - 0.1))
      const marker = diagram.querySelector('marker'), box = marker.querySelector('path').getBBox()
      const tipExtension = (box.x + box.width - marker.refX.baseVal.value) * marker.markerWidth.baseVal.value / marker.viewBox.baseVal.width * Number.parseFloat(getComputedStyle(line).strokeWidth)
      const tailLength = Math.hypot(last.x - before.x, last.y - before.y)
      const tip = new DOMPoint(last.x + tipExtension * (last.x - before.x) / tailLength, last.y + tipExtension * (last.y - before.y) / tailLength)
      return [['source', flow.source, first], ['target', flow.target, tip]].map(([side, id, point]) => {
        const node = diagram.querySelector(`[data-process-node="${id}"]`), card = node.querySelector('.node-card')
        const bounds = card.getBoundingClientRect(), screenPoint = new DOMPoint(point.x, point.y).matrixTransform(matrix)
        let expectedX
        if (!readonly) {
          const port = node.querySelector(side === 'target' ? '.port.input' : id === 'decision' ? `.port.output-${flow.condition !== null ? 'true' : 'false'}` : '.port.output')
          const handle = port.getBoundingClientRect(), scale = handle.width / port.offsetWidth
          const radius = Number.parseFloat(getComputedStyle(port, '::before').width) * scale / 2
          // Connections meet the circular handle in any direction, including a bottom exit.
          return { flow: flow.id, side, gap: Math.abs(Math.hypot(screenPoint.x - handle.x - handle.width / 2,
            screenPoint.y - handle.y - handle.height / 2) - radius) }
        } else if (node.classList.contains('if') || node.classList.contains('parallel')) {
          const halfWidth = bounds.width / 2 - Math.abs(screenPoint.y - (bounds.y + bounds.height / 2))
          expectedX = bounds.x + bounds.width / 2 + (side === 'source' ? halfWidth : -halfWidth)
        } else expectedX = side === 'source' ? bounds.right : bounds.left
        return { flow: flow.id, side, gap: Math.abs(screenPoint.x - expectedX) }
      })
    })
  }, { flows: value.flows, readonly })
  for (const result of gaps) expect(result.gap, `${result.flow} ${result.side}`).toBeLessThan(0.75)
  await page.screenshot({ path: test.info().outputPath(`sequence-arrows-${readonly ? 'elements' : 'handles'}.png`), animations: 'disabled' })
})

test('a new workflow can be built from its start handle and retains typed human assignments', async ({ page }) => {
  await jsonRoute(page, '**/api/processes/internal/agents', [{ id: 7, label: 'Synthetic agent' }])
  await jsonRoute(page, '**/api/processes/internal/owner-options', [
    { kind: 'user', id: 1, label: 'Synthetic owner', is_current_user: true },
    { kind: 'agent', id: 7, label: 'Synthetic agent', has_avatar: false },
  ])
  await jsonRoute(page, '**/api/processes/internal/humans?**', [{ id: 11, label: 'Synthetic human' }])
  let sharing = { lock_version: 1, can_manage: true, grants: [], owner_groups: [], level: 'private', can_write: false,
    owner: { kind: 'user', id: 1, label: 'Synthetic owner', can_write: true },
    options: [{ kind: 'user', id: 11, label: 'Synthetic human', can_write: false }, { kind: 'agent', id: 7, label: 'Synthetic agent', can_write: false }] }
  await page.route('**/api/processes/internal/sharing-options?**', route => route.fulfill({ json: sharing }))
  await jsonRoute(page, '**/api/processes/internal/runs?**', { items: [], total: 0, page: 1, page_size: 50 })
  await mount(page, 'app/process/components/NativeProcessEditor.vue', { privileges: ['PROCESS_READ', 'PROCESS_EDIT'] })
  await expect(page.getByRole('button', { name: 'Start · start', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'End · end', exact: true })).toBeVisible()
  await page.getByRole('combobox', { name: 'Sharing', exact: true }).click()
  await page.getByRole('button', { name: 'Synthetic human: Write', exact: true }).click()
  await page.getByRole('button', { name: 'Synthetic agent: Read', exact: true }).click()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'New actor', exact: true }).click()
  await page.getByText('Add a human actor', { exact: true }).click()
  await page.getByRole('textbox', { name: 'Role name', exact: true }).fill('Reviewer')
  await page.getByRole('combobox', { name: 'Assigned human' }).click()
  await page.getByRole('option', { name: 'Synthetic human', exact: true }).click()
  await page.getByRole('button', { name: 'Output of Start', exact: true }).click()
  await page.getByText('Human task', { exact: true }).click()
  await page.getByRole('dialog', { name: 'Activity settings', exact: true }).getByRole('textbox', { name: 'Title', exact: true }).fill('Review invented result')
  await page.getByRole('textbox', { name: 'Task instructions', exact: true }).fill('Approve an invented result.')
  await page.getByRole('button', { name: 'Close settings', exact: true }).click()
  const writes = []
  const shareWrites = []
  let definition
  await page.route('**/api/processes/internal/definitions', async route => {
    writes.push(route.request().postDataJSON())
    definition = { ...writes[0], owner: sharing.owner, can_manage: true, lock_version: 1, id: 1, code: 'synthetic_saved',
      revision: 1, can_write: true, archived: false, xml: '', diagnostics: [] }
    await route.fulfill({ status: 201, json: definition })
  })
  await page.route('**/api/processes/internal/definitions/synthetic_saved', async route => {
    const update = route.request().postDataJSON()
    if (update.expected_revision !== definition.revision) return route.fulfill({ status: 409, json: { detail: 'Synthetic revision conflict' } })
    definition = { ...definition, ...update, revision: definition.revision + 1 }
    await route.fulfill({ json: definition })
  })
  await page.route('**/api/processes/internal/definitions/synthetic_saved/sharing', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: sharing })
    const update = route.request().postDataJSON(); shareWrites.push(update)
    if (shareWrites.length < 3) return route.fulfill({ status: 500, json: { detail: 'Synthetic sharing failure' } })
    sharing = { ...sharing, ...update, grants: update.grants.map(grant => ({ ...sharing.options.find(option => option.kind === grant.kind && option.id === grant.id), ...grant })), lock_version: 2 }
    return route.fulfill({ json: sharing })
  })
  await page.locator('.editor-content').getByRole('textbox', { name: 'Title', exact: true }).fill('Synthetic review')
  await page.getByRole('textbox', { name: 'Description', exact: true }).fill('Review an entirely invented result.')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  await expect(page.getByRole('alert')).toContainText('Synthetic sharing failure')
  await expect(page.getByRole('combobox', { name: 'Sharing', exact: true })).toContainText('Synthetic human')
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect.poll(() => shareWrites.length).toBe(2)
  await expect(page.getByRole('alert')).toContainText('Synthetic sharing failure')
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect.poll(() => shareWrites.length).toBe(3)
  expect(writes).toHaveLength(1)
  expect(writes[0].description).toBe('Review an entirely invented result.')
  await expect(page.getByRole('textbox', { name: 'Description', exact: true })).toHaveValue('Review an entirely invented result.')
  expect(shareWrites[2]).toMatchObject({ level: 'private', grants: [{ kind: 'user', id: 11, can_write: true }, { kind: 'agent', id: 7, can_write: false }] })
  await expect(page.getByRole('alert')).toHaveCount(0)
  const submitted = writes[0].graph
  expect(submitted.actors[0]).toMatchObject({ name: 'Reviewer', kind: 'human', user_id: 11, agent_id: null })
  const task = submitted.nodes.find(node => node.kind === 'human_task')
  expect(task.config).toMatchObject({ actor: submitted.actors[0].id, prompt: 'Approve an invented result.' })
  expect(submitted.flows).toEqual([expect.objectContaining({ source: 'start', target: task.id }),
    expect.objectContaining({ source: task.id, target: submitted.nodes.find(node => node.kind === 'end').id })])
})

test('handle menus insert into an existing flow without losing its condition or destination', async ({ page }) => {
  const value = graph()
  value.nodes[1].kind = 'if'; value.flows[1].condition = 'input.ready'
  await mount(page, 'app/process/components/BpmnCanvas.vue', { props: { modelValue: value } })
  await page.getByRole('button', { name: 'True output of Conditional choice', exact: true }).click()
  await page.getByRole('button', { name: 'Task', exact: true }).click()
  await expect(page.getByText('Continue the process', { exact: true })).toHaveCount(0)
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value.flows)).toMatchObject([
    { source: 'start', target: 'work' }, { id: 'f2', source: 'work', condition: 'input.ready' }, { target: 'end', condition: null },
  ])
  const saved = await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1).value)
  expect(saved.flows[1].target).toBe(saved.nodes.at(-1).id)
  expect(saved.flows[2].source).toBe(saved.nodes.at(-1).id)
  await page.evaluate(graph => window.testApp.setProps({ modelValue: graph }), value)
  await page.getByRole('button', { name: 'Input of End', exact: true }).click()
  await page.getByRole('button', { name: 'Task', exact: true }).click()
  const before = await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1).value)
  // The decision's condition stays on work -> inserted, followed by inserted -> end.
  expect(before.flows.find(flow => flow.id === 'f2')).toMatchObject({ source: 'work', target: before.nodes.at(-1).id, condition: 'input.ready' })
  expect(before.flows.at(-1)).toMatchObject({ source: before.nodes.at(-1).id, target: 'end', condition: null })
})

test('ordinary activities can branch and converge directly without a dedicated gateway', async ({ page }) => {
  const value = graph()
  value.schema_version = 'galaris.bpmn/v2'; value.inputs = []; value.outputs = []
  await mount(page, 'app/process/components/BpmnCanvas.vue', { props: { modelValue: value } })
  const lastGraph = () => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value)
  await page.getByRole('button', { name: 'Output of Task', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Parallel gateway', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Add a branch', exact: true }).click()
  await page.getByRole('button', { name: 'Task', exact: true }).last().click()
  await expect.poll(lastGraph).toBeTruthy()
  const branched = await lastGraph(), branch = branched.nodes.at(-1)
  expect(branch.kind).toBe('task')
  expect(branched.flows.filter(flow => flow.source === 'work').map(flow => flow.target).sort()).toEqual([branch.id, 'end'].sort())
  await page.keyboard.press('Escape')
  await expect(page.getByText('Continue the process', { exact: true })).toHaveCount(0)
  await page.evaluate(modelValue => window.testApp.setProps({ modelValue }), branched)
  await page.locator(`[data-process-node="${branch.id}"]`).getByRole('button', { name: 'Output of Task', exact: true }).click()
  await page.getByRole('button', { name: 'Connect to an activity', exact: true }).click()
  await page.getByRole('button', { name: 'End · end', exact: true }).click()
  await expect.poll(async () => (await lastGraph()).flows.filter(flow => flow.target === 'end').map(flow => flow.source).sort()).toEqual(['work', branch.id].sort())
  const joined = await lastGraph()
  expect(joined.nodes.every(node => node.kind !== 'parallel')).toBe(true)
  await page.evaluate(modelValue => window.testApp.setProps({ modelValue }), joined)
  await page.screenshot({ path: test.info().outputPath('ordinary-parallel-branches.png'), animations: 'disabled' })
})

test('typed actor lanes preserve task assignment when editing and saving', async ({ page }) => {
  const writes = await definitionFixtures(page, true)
  const value = graph()
  value.actors = [
    { id: 'executor', name: 'Executor', kind: 'agent', agent_id: 7, user_id: null },
    { id: 'reviewer', name: 'Reviewer', kind: 'human', user_id: 11, agent_id: null },
  ]
  value.nodes[1].config.actor = 'executor'; value.nodes[1].title = 'Prepare a synthetic business decision'
  value.nodes.splice(2, 0, { id: 'review', kind: 'human_task', title: 'Review the proposed decision', config: { actor: 'reviewer', prompt: 'Review invented data.' }, body: null, x: 780, y: 0 })
  value.nodes.at(-1).x = 1060
  value.flows[1].target = 'review'; value.flows.push({ id: 'f3', source: 'review', target: 'end', condition: null })
  await page.route('**/api/processes/internal/definitions/invented_process', async route => {
    const saving = route.request().method() === 'PUT'
    const update = saving ? route.request().postDataJSON() : {}
    if (saving) writes.push(update)
    await route.fulfill({ json: { id: 1, code: 'invented_process', title: 'Synthetic actor workflow',
      revision: saving ? 2 : 1, archived: false, can_write: true,
      graph: value, xml: '<synthetic/>', diagnostics: [], ...update } })
  })
  await mount(page, 'app/process/components/NativeProcessEditor.vue', { props: { code: 'invented_process' }, privileges: ['PROCESS_READ', 'PROCESS_EDIT'] })
  await page.getByRole('button', { name: 'Fit the diagram', exact: true }).click()
  await page.getByRole('button', { name: 'Prepare a synthetic business decision · work', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Activity settings', exact: true })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('actor-editor-light.png'), fullPage: true, animations: 'disabled' })
  await page.evaluate(() => window.testApp.dark(true))
  await page.screenshot({ path: test.info().outputPath('actor-editor-dark.png'), fullPage: true, animations: 'disabled' })
  await page.getByRole('button', { name: 'Close settings', exact: true }).click()
  await page.getByRole('button', { name: 'View process in full screen', exact: true }).click()
  await page.getByRole('button', { name: 'Prepare a synthetic business decision · work', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Activity settings', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Close settings', exact: true }).click()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].graph.nodes.find(node => node.id === 'work').config.actor).toBe('executor')
  await page.getByRole('button', { name: 'Exit full screen', exact: true }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Prepare a synthetic business decision · work', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Activity settings', exact: true }).getByRole('textbox', { name: 'Title', exact: true })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('actor-form-mobile.png'), fullPage: true, animations: 'disabled' })
  await page.getByRole('button', { name: 'Close settings', exact: true }).click()
  await page.getByRole('button', { name: 'Output of Start', exact: true }).click()
  await expect(page.getByText('Continue the process', { exact: true })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('actor-editor-mobile.png'), fullPage: true, animations: 'disabled' })
})

async function definitionFixtures(page, writable, kind = 'task', typed = false, declarations = {}, definitionRevision = 1) {
  const definition = { id: 1, code: 'invented_process', title: 'Invented workflow', description: 'Synthetic existing description',
    owner: { kind: 'agent', id: 7, label: 'Synthetic agent', has_avatar: false }, can_manage: writable, lock_version: 1,
    revision: definitionRevision, archived: false, can_write: writable, graph: graph(), xml: '<synthetic/>', diagnostics: [] }
  const writes = []
  definition.graph.nodes[1].kind = kind
  if (typed) {
    definition.graph.schema_version = 'galaris.bpmn/v2'
    definition.graph.inputs = []; definition.graph.outputs = []
    definition.graph.nodes[1].inputs = declarations.inputs ?? []; definition.graph.nodes[1].outputs = declarations.outputs ?? []
  }
  if (kind === 'tool_call') definition.graph.nodes[1].config = { tool: 'synthetic_tool' }
  await jsonRoute(page, '**/api/processes/internal/agents', [{ id: 7, label: 'Synthetic agent' }])
  await jsonRoute(page, '**/api/processes/internal/owner-options', [
    { kind: 'user', id: 1, label: 'Synthetic owner', is_current_user: true },
    { kind: 'agent', id: 7, label: 'Synthetic agent', has_avatar: false },
  ])
  await jsonRoute(page, '**/api/processes/internal/humans?**', [{ id: 11, label: 'Synthetic human' }])
  await jsonRoute(page, '**/api/processes/internal/definitions/invented_process/sharing', { lock_version: 1, can_manage: writable, can_write: writable,
    grants: [], options: [], level: 'private', owner: { kind: 'agent', id: 7, label: 'Synthetic agent', can_write: true }, owner_groups: [] })
  await jsonRoute(page, '**/api/processes/internal/runs?*', { items: [], total: 0, page: 1, page_size: 50 })
  await page.route('**/api/processes/internal/definitions/invented_process', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: definition })
    writes.push(route.request().postDataJSON())
    return route.fulfill({ json: { ...definition, ...writes.at(-1), revision: 2 } })
  })
  return writes
}

test('process owner options refresh on reopening after five minutes without losing the draft', async ({ page }) => {
  await page.clock.install()
  await definitionFixtures(page, true)
  let reads = 0
  await page.route('**/api/processes/internal/owner-options', route => {
    reads++
    return route.fulfill({ json: [
      { kind: 'user', id: 1, label: 'Synthetic owner', is_current_user: true },
      { kind: 'agent', id: 7, label: `Synthetic agent ${reads}`, has_avatar: false },
    ] })
  })
  await mount(page, 'app/process/components/NativeProcessEditor.vue', { props: { code: 'invented_process' }, privileges: ['PROCESS_EDIT'] })
  const picker = page.getByRole('combobox', { name: 'Owner', exact: true })
  const title = page.locator('.editor-content').getByRole('textbox', { name: 'Title', exact: true })
  await expect(picker).toBeEnabled()
  await title.fill('Synthetic unsaved draft')
  for (let opening = 0; opening < 3; opening++) {
    await picker.click()
    await expect(page.getByRole('option', { name: 'Synthetic agent 1', exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
  }
  expect(reads).toBe(1)
  await page.clock.fastForward(300_001)
  await picker.click()
  await expect(page.getByRole('option', { name: 'Synthetic agent 2', exact: true })).toBeVisible()
  expect(reads).toBe(2)
  await page.keyboard.press('Escape')
  await expect(title).toHaveValue('Synthetic unsaved draft')
})

test('process owner conflicts preserve drafts and a successful transfer refreshes sharing without changing the diagram', async ({ page }) => {
  const writes = await definitionFixtures(page, true)
  let fail = true
  const original = { kind: 'agent', id: 7, label: 'Synthetic agent', has_avatar: false }
  const target = { kind: 'user', id: 1, label: 'Synthetic owner', is_current_user: true }
  let currentOwner = original, lockVersion = 1
  const transfers = [], sharingReads = []
  await page.route('**/api/processes/internal/definitions/invented_process/owner', route => {
    transfers.push(route.request().postDataJSON())
    if (fail) return route.fulfill({ status: 409, json: { detail: 'Synthetic ownership conflict' } })
    // Another editor saves content after the ownership transaction commits,
    // before the API rereads the definition for its response.
    currentOwner = target; lockVersion += 2
    const remoteGraph = graph(); remoteGraph.nodes[1].config.prompt = 'A newer synthetic saved instruction'
    return route.fulfill({ json: { id: 1, code: 'invented_process', title: 'Invented workflow', description: 'Synthetic existing description',
      revision: 2, archived: false, can_write: true, can_manage: true, lock_version: lockVersion,
      owner: currentOwner, graph: remoteGraph, xml: '<synthetic/>', diagnostics: [] } })
  })
  await page.route('**/api/processes/internal/definitions/invented_process/sharing', route => {
    sharingReads.push(lockVersion)
    return route.fulfill({ json: { lock_version: lockVersion, can_manage: true, can_write: false,
      grants: currentOwner === original ? [] : [{ ...original, can_write: true }], options: [], level: 'private', owner: currentOwner, owner_groups: [] } })
  })
  await page.route('**/api/processes/internal/definitions/invented_process', route => {
    if (route.request().method() !== 'PUT') return route.fallback()
    writes.push(route.request().postDataJSON())
    return route.fulfill({ status: 409, json: { detail: 'Synthetic graph revision changed' } })
  })
  await mount(page, 'app/process/components/NativeProcessEditor.vue', { props: { code: 'invented_process' }, privileges: ['PROCESS_EDIT'] })
  const picker = page.getByRole('combobox', { name: 'Owner', exact: true })
  const title = page.locator('.editor-content').getByRole('textbox', { name: 'Title', exact: true })
  let pendingPrivileges
  await page.route('**/api/authorize/my-privileges', route => { pendingPrivileges = route })
  await page.evaluate(() => { window.testApp.privileges.clearPrivileges(); void window.testApp.privileges.loadPrivileges() })
  await expect.poll(() => Boolean(pendingPrivileges)).toBe(true)
  await expect(picker).toBeDisabled()
  await pendingPrivileges.fulfill({ json: ['PROCESS_EDIT'] })
  await expect(picker).toBeEnabled()
  await title.fill('Unsaved synthetic title')
  await page.getByRole('textbox', { name: 'Description', exact: true }).fill('Unsaved synthetic description')
  await picker.click(); await page.getByRole('option', { name: 'Me', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Synthetic ownership conflict' })).toBeVisible()
  await expect(picker).toContainText(original.label)
  await expect(title).toHaveValue('Unsaved synthetic title')
  fail = false
  await picker.click(); await page.getByRole('option', { name: 'Me', exact: true }).click()
  await expect(picker).toContainText('Me')
  await expect.poll(() => sharingReads).toContain(3)
  await expect(title).toHaveValue('Unsaved synthetic title')
  await expect(page.getByRole('textbox', { name: 'Description', exact: true })).toHaveValue('Unsaved synthetic description')
  expect(transfers).toEqual([{ kind: 'user', id: 1, expected_lock_version: 1 }, { kind: 'user', id: 1, expected_lock_version: 1 }])
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  await expect(page.getByRole('alert').filter({ hasText: 'Synthetic graph revision changed' })).toBeVisible()
  await expect(title).toHaveValue('Unsaved synthetic title')
  expect(writes[0]).toMatchObject({ title: 'Unsaved synthetic title', description: 'Unsaved synthetic description', expected_revision: 1 })
  expect(writes[0].graph.nodes.map(node => ({ id: node.id, config: node.config }))).toEqual(graph().nodes.map(node => ({ id: node.id, config: node.config })))
})

for (const width of [1440, 390]) {
test(`process history paginates saved revisions and retries without losing the editing draft at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 })
  const writes = await definitionFixtures(page, true, 'task', false, {}, 76)
  const requests = []
  let rejectNextPage = true
  let rejectNextRevision = true
  await page.route('**/api/processes/internal/definitions/invented_process/history/11', async route => {
    if (rejectNextRevision) {
      rejectNextRevision = false
      return route.fulfill({ status: 503, json: { detail: 'Synthetic revision unavailable' } })
    }
    return route.fulfill({ json: { detail: { content: '<synthetic-saved-revision/>' } } })
  })
  const savedGraph = graph()
  savedGraph.nodes[1].title = 'Previous synthetic activity'
  await jsonRoute(page, '**/api/processes/internal/validate', { graph: savedGraph, xml: '<synthetic-saved-revision/>' })
  await page.route('**/api/processes/internal/definitions/invented_process/history?**', async route => {
    const url = new URL(route.request().url())
    const pageNumber = Number(url.searchParams.get('page')), pageSize = Number(url.searchParams.get('page_size'))
    requests.push({ page: pageNumber, pageSize })
    if (pageNumber === 2 && rejectNextPage) {
      rejectNextPage = false
      return route.fulfill({ status: 503, json: { detail: 'Synthetic history unavailable' } })
    }
    const start = (pageNumber - 1) * pageSize
    return route.fulfill({ json: {
      items: Array.from({ length: Math.min(pageSize, 75 - start) }, (_, index) => ({
        revision: start + index + 1, author_agent_id: 7, created_at: new Date(Date.UTC(2026, 0, start + index + 1, 12)).toISOString(),
      })), total: 75, has_more: start + pageSize < 75,
    } })
  })
  await mount(page, 'app/process/components/NativeProcessEditor.vue', { props: { code: 'invented_process' }, privileges: ['PROCESS_READ', 'PROCESS_EDIT'] })
  const title = page.getByRole('textbox', { name: 'Title', exact: true })
  await title.fill('Unsaved synthetic process title')
  expect(requests).toEqual([])
  await page.getByText('Process history', { exact: true }).click()
  const history = page.getByLabel('Process history', { exact: true })
  await expect(history.getByRole('row')).toHaveCount(50)
  expect(requests).toEqual([{ page: 1, pageSize: 50 }])
  await history.getByRole('combobox').click()
  await page.getByRole('option', { name: '10', exact: true }).click()
  await expect(history.getByText('1–10 of 75', { exact: true })).toBeVisible()
  await expect(history.getByRole('row')).toHaveCount(10)
  await history.getByRole('button', { name: 'Next page', exact: true }).click()
  const error = page.getByRole('alert').filter({ hasText: 'Unable to complete this action' })
  await expect(error).toBeVisible()
  await expect(title).toHaveValue('Unsaved synthetic process title')
  await error.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(history.getByText('11–20 of 75', { exact: true })).toBeVisible()
  await expect(history.getByRole('button', { name: /Jan 11, 2026/ })).toBeVisible()
  await expect(error).toHaveCount(0)
  expect(requests.slice(-2)).toEqual([{ page: 2, pageSize: 10 }, { page: 2, pageSize: 10 }])
  const comparison = page.getByRole('region', { name: 'Revision diagram', exact: true })
  await expect(comparison).toContainText('Select a revision')
  const inspect = history.getByRole('button', { name: /Jan 11, 2026/ })
  if (width === 1440) await inspect.click()
  else { await inspect.focus(); await page.keyboard.press('Enter') }
  await expect(comparison.getByRole('alert')).toBeVisible()
  await comparison.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(comparison.getByRole('button', { name: 'Previous synthetic activity · work', exact: true })).toBeVisible()
  await expect(inspect).toHaveAttribute('aria-pressed', 'true')
  await expect(comparison.getByRole('alert')).toHaveCount(0)
  await page.locator('.history-workspace').screenshot({ path: test.info().outputPath('process-history-comparison.png'), animations: 'disabled' })
  await history.getByRole('button', { name: 'Previous page', exact: true }).click()
  await expect(history.getByText('1–10 of 75', { exact: true })).toBeVisible()
  await expect(title).toHaveValue('Unsaved synthetic process title')
  expect(writes).toEqual([])
})
}

test('saved process states require confirmation, preserve drafts on failure and keep mutations separate from inspection', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 1000 })
  await definitionFixtures(page, true, 'task', false, {}, 3)
  let entries = [2, 1].map(revision => ({ revision, author_agent_id: 7, created_at: `2026-01-0${revision}T12:00:00Z` }))
  const deletes = [], restores = [], inspections = []
  let failDelete = true
  await page.route('**/api/processes/internal/definitions/invented_process/history?**', route => {
    expect(new URL(route.request().url()).searchParams.get('exclude_current')).toBe('true')
    return route.fulfill({ json: { items: entries, total: entries.length, has_more: false } })
  })
  await page.route('**/api/processes/internal/definitions/invented_process/history/2', route => {
    if (route.request().method() === 'GET') {
      inspections.push(2)
      return route.fulfill({ json: { detail: { content: '<synthetic-history/>' } } })
    }
    expect(route.request().method()).toBe('DELETE')
    deletes.push(2)
    if (failDelete) {
      failDelete = false
      return route.fulfill({ status: 503, json: { detail: 'Synthetic deletion unavailable' } })
    }
    entries = entries.filter(entry => entry.revision !== 2)
    return route.fulfill({ status: 204 })
  })
  const historical = graph()
  historical.nodes[1].title = 'Historical synthetic activity'
  await jsonRoute(page, '**/api/processes/internal/validate', { graph: historical, xml: '<synthetic-history/>' })
  await mount(page, 'app/process/components/NativeProcessEditor.vue', { props: { code: 'invented_process' }, privileges: ['PROCESS_READ', 'PROCESS_EDIT'] })
  const saved = await page.evaluate(async () => (await fetch('/api/processes/internal/definitions/invented_process')).json())
  await page.route('**/api/processes/internal/definitions/invented_process/restore', route => {
    restores.push(route.request().postDataJSON())
    entries = [{ revision: 3, author_agent_id: 7, created_at: '2026-01-03T12:00:00Z' }, ...entries]
    return route.fulfill({ json: { ...saved, revision: 4, graph: historical } })
  })
  const title = page.getByRole('textbox', { name: 'Title', exact: true })
  await title.fill('Unsaved synthetic history draft')
  await page.getByText('Process history', { exact: true }).click()
  const history = page.getByLabel('Process history', { exact: true })
  const state = history.getByRole('button', { name: /Jan 2, 2026/ })
  const comparison = page.getByRole('region', { name: 'Revision diagram', exact: true })
  await state.click()
  await expect(comparison.getByRole('button', { name: 'Historical synthetic activity · work', exact: true })).toBeVisible()
  const restore = state.getByRole('button', { name: 'Return to this state', exact: true })
  await restore.focus(); await page.keyboard.press('Enter')
  const restoreDialog = page.getByRole('dialog', { name: 'Return to this state', exact: true })
  await expect(restoreDialog).toContainText('Unsaved changes will be lost.')
  await expect(restoreDialog).toContainText('Existing history and runs will be preserved.')
  expect(restores).toEqual([])
  expect(inspections).toEqual([2])
  await restoreDialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(title).toHaveValue('Unsaved synthetic history draft')
  const remove = state.getByRole('button', { name: 'Delete this saved state', exact: true })
  const deleteDialog = page.getByRole('dialog', { name: 'Delete this saved state', exact: true })
  await remove.click()
  await expect(deleteDialog).toContainText('permanently deleted')
  expect(deletes).toEqual([])
  await deleteDialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await remove.click()
  await deleteDialog.getByRole('button', { name: 'Delete this saved state', exact: true }).click()
  const error = page.getByRole('alert').filter({ hasText: 'Unable to complete this action' })
  await expect(error).toBeVisible()
  await expect(title).toHaveValue('Unsaved synthetic history draft')
  await expect(state).toBeVisible()
  await error.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(error).toHaveCount(0)
  await remove.click()
  await deleteDialog.getByRole('button', { name: 'Delete this saved state', exact: true }).click()
  await expect(state).toHaveCount(0)
  await expect(comparison).toContainText('Select a revision')
  await expect(title).toHaveValue('Unsaved synthetic history draft')
  expect(deletes).toEqual([2, 2])
  expect(inspections).toEqual([2])
  const first = history.getByRole('button', { name: /Jan 1, 2026/ })
  await first.getByRole('button', { name: 'Return to this state', exact: true }).click()
  await restoreDialog.screenshot({ path: test.info().outputPath('confirm-process-state-restore.png'), animations: 'disabled' })
  await restoreDialog.getByRole('button', { name: 'Return to this state', exact: true }).click()
  await expect(title).toHaveValue('Invented workflow')
  expect(restores).toEqual([{ revision: 1, expected_revision: 3 }])
})

for (const initialMode of ['ai', null]) {
test(`binary IF exposes two branches and processing follows its actor (${initialMode ?? 'historical expression'})`, async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1400 })
  const writes = await definitionFixtures(page, true)
  const value = graph()
  value.schema_version = 'galaris.bpmn/v2'; value.inputs = []; value.outputs = []
  value.actors = [{ id: 'executor', name: 'Executor', kind: 'agent', agent_id: 7, user_id: null },
    { id: 'reviewer', name: 'Reviewer', kind: 'human', agent_id: null, user_id: 11 }]
  value.nodes[1] = { ...value.nodes[1], kind: 'if', title: 'Check project', config: { actor: 'executor', ...(initialMode ? { mode: initialMode } : {}), prompt: 'Check the project name.' } }
  value.nodes.push({ id: 'declined', kind: 'end', title: '', config: {}, body: null, x: 780, y: 300 })
  value.flows[1].condition = initialMode ? 'decision' : 'input.ready'; value.flows.push({ id: 'no', source: 'work', target: 'declined', condition: null })
  await page.route('**/api/processes/internal/definitions/invented_process', async route => {
    const saving = route.request().method() === 'PUT', update = saving ? route.request().postDataJSON() : {}
    if (saving) writes.push(update)
    await route.fulfill({ json: { id: 1, code: 'invented_process', title: 'Synthetic decision', revision: saving ? 2 : 1,
      archived: false, can_write: true, graph: value, xml: '<synthetic/>', diagnostics: [], ...update } })
  })
  await mount(page, 'app/process/components/NativeProcessEditor.vue', { props: { code: 'invented_process' }, privileges: ['PROCESS_READ', 'PROCESS_EDIT'] })
  await expect(page.getByRole('button', { name: 'True output of Check project', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'False output of Check project', exact: true })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('binary-if-diagram.png'), fullPage: true, animations: 'disabled' })
  for (const [branch, destination] of [['True', 'End · declined'], ['False', 'End · end']]) {
    await page.getByRole('button', { name: `${branch} output of Check project`, exact: true }).click()
    await page.getByText('Connect to an activity', { exact: true }).click()
    await page.getByRole('button', { name: destination, exact: true }).click()
    await page.getByRole('button', { name: 'Close settings', exact: true }).click()
  }
  const activity = page.getByRole('button', { name: 'Check project · work', exact: true })
  await activity.click()
  const mode = page.getByRole('combobox', { name: 'Processing', exact: true })
  await mode.click(); await page.getByRole('option', { name: 'Code', exact: true }).click()
  const code = page.getByRole('textbox', { name: 'Python program', exact: true })
  await code.fill('return variable_2 != "pas mon projet"')
  await mode.click(); await page.getByRole('option', { name: 'AI', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Task instructions', exact: true })).toHaveValue('Check the project name.')
  await mode.click(); await page.getByRole('option', { name: 'Code', exact: true }).click()
  await expect(code).toHaveValue('return variable_2 != "pas mon projet"')
  await page.getByRole('button', { name: 'Close settings', exact: true }).click()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].graph.nodes.find(node => node.id === 'work').config).toMatchObject({ mode: 'code', actor: 'executor', code: 'return variable_2 != "pas mon projet"' })
  expect(writes[0].graph.flows.filter(flow => flow.source === 'work')).toEqual([
    { id: 'f2', source: 'work', target: 'declined', condition: 'decision' },
    { id: 'no', source: 'work', target: 'end', condition: null },
  ])
  const source = await activity.boundingBox(), lane = await page.locator('.swimlane').filter({ has: page.getByRole('button', { name: 'Remove actor Reviewer', exact: true }) }).boundingBox()
  await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2); await page.mouse.down()
  await page.mouse.move(source.x + source.width / 2, lane.y + lane.height / 2, { steps: 8 }); await page.mouse.up()
  await activity.click()
  await expect(mode).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: 'Task instructions', exact: true })).toHaveValue('Check the project name.')
  await page.getByRole('dialog').screenshot({ path: test.info().outputPath('human-if.png'), animations: 'disabled' })
  await page.getByRole('button', { name: 'Close settings', exact: true }).click()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(2)
  expect(writes[1].graph.nodes.find(node => node.id === 'work').config).toMatchObject({ mode: 'human', actor: 'reviewer' })
})
}

test('typed tasks switch between AI and Dataset code without losing instructions', async ({ page }) => {
  const writes = await definitionFixtures(page, true, 'task', true)
  await mount(page, 'app/process/components/NativeProcessEditor.vue', { props: { code: 'invented_process' }, privileges: ['PROCESS_READ', 'PROCESS_EDIT'] })
  await page.getByRole('button', { name: 'Task · work', exact: true }).click()
  const mode = page.getByRole('combobox', { name: 'Processing', exact: true })
  await mode.click(); await page.getByRole('option', { name: 'Code', exact: true }).click()
  const code = page.getByRole('textbox', { name: 'Python program', exact: true })
  await expect(code).toHaveValue(/# Example:/)
  await code.fill('return {"variable_1": variable_1 + 1}')
  await mode.click(); await page.getByRole('option', { name: 'AI', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Task instructions', exact: true })).toHaveValue('Prepare an invented result')
  await mode.click(); await page.getByRole('option', { name: 'Code', exact: true }).click()
  await expect(code).toHaveValue('return {"variable_1": variable_1 + 1}')
  await page.getByRole('dialog').screenshot({ path: test.info().outputPath('dataset-code-task.png'), animations: 'disabled' })
  await page.getByRole('button', { name: 'Close settings', exact: true }).click()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].graph.nodes.find(node => node.id === 'work')).toMatchObject({ kind: 'code', config: { dataset_code: true, prompt: 'Prepare an invented result', code: 'return {"variable_1": variable_1 + 1}' } })
})

test('typed activity declarations preserve defaults and invalid drafts through reopening', async ({ page }) => {
  const writes = await definitionFixtures(page, true, 'task', true)
  await mount(page, 'app/process/components/NativeProcessEditor.vue', { props: { code: 'invented_process' }, privileges: ['PROCESS_READ', 'PROCESS_EDIT'] })
  await page.getByRole('button', { name: 'Task · work', exact: true }).click()
  const outputs = page.getByRole('region', { name: 'Output variables', exact: true })
  await outputs.getByRole('button', { name: 'Add a variable', exact: true }).click()
  await outputs.getByRole('textbox', { name: 'Name', exact: true }).fill('accepted')
  await outputs.getByRole('combobox', { name: 'Type', exact: true }).click()
  await page.getByRole('option', { name: 'bool', exact: true }).click()
  await outputs.getByRole('switch', { name: 'Nullable', exact: true }).uncheck()
  const value = outputs.getByRole('textbox', { name: 'Default value', exact: true })
  await value.fill('{')
  await page.getByRole('button', { name: 'Close settings', exact: true }).click()
  await page.getByRole('button', { name: 'Task · work', exact: true }).click()
  await expect(value).toHaveValue('{')
  await page.getByRole('button', { name: 'Close settings', exact: true }).click()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  expect(writes).toHaveLength(0)
  await page.getByRole('button', { name: 'Task · work', exact: true }).click()
  await value.fill('false')
  await page.getByRole('button', { name: 'Close settings', exact: true }).click()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].graph.nodes.find(node => node.id === 'work').outputs).toEqual([
    { name: 'accepted', type: 'bool', nullable: false, default: { type: 'bool', value: false } },
  ])
  await page.getByRole('button', { name: 'Task · work', exact: true }).click()
  await expect(value).toHaveValue('false')
  await expect(outputs.getByRole('switch', { name: 'Nullable', exact: true })).not.toBeChecked()
  await page.getByRole('dialog').screenshot({ path: test.info().outputPath('typed-activity-declarations.png'), animations: 'disabled' })
  await value.fill('')
  await page.getByRole('button', { name: 'Close settings', exact: true }).click()
  await page.getByRole('button', { name: 'Task · work', exact: true }).click()
  await expect(value).toHaveValue('')
  await page.getByRole('button', { name: 'Close settings', exact: true }).click()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(2)
  expect(writes[1].graph.nodes.find(node => node.id === 'work').outputs).toEqual([
    { name: 'accepted', type: 'bool', nullable: false },
  ])
})

test('variable defaults preserve explicit JSON values and clear to omission', async ({ page }) => {
  const values = [
    { name: 'count', type: 'int', value: 0 }, { name: 'accepted', type: 'bool', value: false },
    { name: 'title', type: 'string', value: '' }, { name: 'items', type: 'array', value: [] },
    { name: 'details', type: 'object', value: {} }, { name: 'optional', type: 'string', value: null },
  ]
  const variables = values.map(({ name, type }) => ({ name, type, nullable: true }))
  await mount(page, 'app/process/components/ProcessVariableDeclarations.vue', {
    props: { modelValue: variables, label: 'Output variables' }, containerStyle: { width: '608px', maxWidth: '100%' },
  })
  const fields = page.getByRole('textbox', { name: 'Default value', exact: true })
  const last = () => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value)
  for (const [index, variable] of values.entries()) await fields.nth(index).fill(JSON.stringify(variable.value))
  await expect.poll(last).toEqual(values.map(({ value, ...variable }) => ({ ...variable, nullable: true, default: { type: variable.type, value } })))
  await page.getByRole('region', { name: 'Output variables' }).screenshot({ path: test.info().outputPath('variable-table-light.png'), animations: 'disabled' })
  await page.evaluate(() => window.testApp.dark(true))
  await page.getByRole('region', { name: 'Output variables' }).screenshot({ path: test.info().outputPath('variable-table-dark.png'), animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('region', { name: 'Output variables' }).screenshot({ path: test.info().outputPath('variable-table-mobile.png'), animations: 'disabled' })
  await fields.first().fill('{')
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'validity').at(-1)?.value)).toBe(false)
  await fields.first().fill(' ')
  await expect.poll(last).toEqual(values.map(({ value, ...variable }, index) => ({ ...variable, nullable: true, ...(index ? { default: { type: variable.type, value } } : {}) })))
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'validity').at(-1)?.value)).toBe(true)
  await page.evaluate(() => window.testApp.setProps({ readonly: true }))
  await expect(fields.first()).toHaveAttribute('readonly', '')
  await expect(page.getByRole('switch', { name: 'Nullable', exact: true }).first()).toBeDisabled()
})

for (const [side, label] of [['inputs', 'Input variables'], ['outputs', 'Output variables']]) {
  test(`${label} can be reordered without losing drafts, defaults or saved order`, async ({ page }) => {
    const variables = [
      { name: 'count', type: 'int', nullable: false, default: { type: 'int', value: 0 } },
      { name: 'accepted', type: 'bool', nullable: false, default: { type: 'bool', value: false } },
      { name: 'title', type: 'string', nullable: true, default: { type: 'string', value: '' } },
    ]
    const writes = await definitionFixtures(page, true, 'task', true, { [side]: variables })
    await mount(page, 'app/process/components/NativeProcessEditor.vue', { props: { code: 'invented_process' }, privileges: ['PROCESS_READ', 'PROCESS_EDIT'] })
    const open = () => page.getByRole('button', { name: 'Task · work', exact: true }).click()
    await open()
    const region = page.getByRole('region', { name: label, exact: true })
    const names = region.getByRole('textbox', { name: 'Name', exact: true })
    const defaults = region.getByRole('textbox', { name: 'Default value', exact: true })
    const expectNames = expected => expect.poll(() => names.evaluateAll(inputs => inputs.map(input => input.value))).toEqual(expected)
    await defaults.first().fill('{')
    async function dragCount(cancel = false) {
      const handle = region.getByRole('button', { name: 'Reorder variable count', exact: true })
      await handle.scrollIntoViewIfNeeded()
      const source = await handle.boundingBox(), target = await region.getByRole('button', { name: 'Reorder variable title', exact: true }).boundingBox()
      await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2)
      await page.mouse.down()
      await page.mouse.move(target.x + target.width / 2, target.y + target.height / 2, { steps: 8 })
      await expectNames(['count', 'accepted', 'title'])
      if (cancel) await page.keyboard.press('Escape')
      await page.mouse.up()
    }
    await dragCount(true)
    await expectNames(['count', 'accepted', 'title'])
    await expect(defaults.first()).toHaveValue('{')
    await dragCount()
    await expectNames(['accepted', 'title', 'count'])
    await expect.poll(() => defaults.evaluateAll(inputs => inputs.map(input => input.value))).toEqual(['false', '""', '{'])
    await page.getByRole('button', { name: 'Close settings', exact: true }).click()
    await open()
    await expect(defaults.last()).toHaveValue('{')
    await page.getByRole('button', { name: 'Close settings', exact: true }).click()
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    expect(writes).toHaveLength(0)
    await open()
    await defaults.last().fill('0')
    await page.getByRole('dialog').screenshot({ path: test.info().outputPath(`reordered-${side}.png`), animations: 'disabled' })
    await page.getByRole('button', { name: 'Close settings', exact: true }).click()
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => writes.length).toBe(1)
    expect(writes[0].graph.nodes.find(node => node.id === 'work')[side]).toEqual([variables[1], variables[2], variables[0]])
    await open()
    const handle = region.getByRole('button', { name: 'Reorder variable count', exact: true })
    await handle.focus(); await page.keyboard.press('ArrowUp')
    await expectNames(['accepted', 'count', 'title'])
    await expect(handle).toBeFocused()
    await page.getByRole('button', { name: 'Close settings', exact: true }).click()
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => writes.length).toBe(2)
    expect(writes[1].graph.nodes.find(node => node.id === 'work')[side]).toEqual([variables[1], variables[0], variables[2]])
  })
}

test('invalid tool argument drafts survive node changes and prevent saving until repaired', async ({ page }) => {
  const writes = await definitionFixtures(page, true, 'tool_call')
  await mount(page, 'app/process/components/NativeProcessEditor.vue', { props: { code: 'invented_process' }, privileges: ['PROCESS_READ', 'PROCESS_EDIT'] })
  await page.getByRole('button', { name: 'Tool operation · work', exact: true }).click()
  const mapping = page.getByRole('textbox', { name: 'Tool arguments (JSON)', exact: true })
  await mapping.fill('{')
  await page.getByRole('button', { name: 'Close settings', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Activity settings', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Tool operation · work', exact: true }).click()
  await expect(mapping).toHaveValue('{')
  await page.getByRole('dialog', { name: 'Activity settings', exact: true }).getByRole('textbox', { name: 'Title', exact: true }).focus()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Activity settings', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Tool operation · work', exact: true }).click()
  await expect(mapping).toHaveValue('{')
  // Click outside the inspector independently of where its popover fits in the viewport.
  await page.getByRole('heading', { name: 'Process editor', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Activity settings', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Tool operation · work', exact: true }).click()
  await page.getByRole('button', { name: 'End · end', exact: true }).click()
  await page.getByRole('button', { name: 'Tool operation · work', exact: true }).click()
  await expect(mapping).toHaveValue('{')
  await page.getByRole('button', { name: 'Close settings', exact: true }).click()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  expect(writes).toEqual([])
  await page.getByRole('button', { name: 'Tool operation · work', exact: true }).click()
  await expect(mapping).toHaveValue('{')
  await mapping.fill('{"amount": 8}')
  await page.getByRole('button', { name: 'Flow from start to work', exact: true }).click()
  const flowForm = page.getByRole('dialog', { name: 'Flow settings', exact: true })
  await expect(flowForm).toBeVisible()
  await page.getByRole('button', { name: 'Close settings', exact: true }).click()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]).toMatchObject({ expected_revision: 1, graph: { nodes: [{ id: 'start' }, { id: 'work', config: { input: { amount: 8 } } }, { id: 'end' }] } })
})

test('archiving requires confirmation and reactivation preserves unsaved process edits', async ({ page }) => {
  const writes = await definitionFixtures(page, true, 'task', true)
  await mount(page, 'app/process/components/NativeProcessEditor.vue', { props: { code: 'invented_process' }, privileges: ['PROCESS_READ', 'PROCESS_EDIT', 'PROCESS_LAUNCH'] })
  const saved = await page.evaluate(async () => (await fetch('/api/processes/internal/definitions/invented_process')).json())
  const archiveWrites = []
  await page.route('**/api/processes/internal/definitions/invented_process/archive?**', async route => {
    const archived = new URL(route.request().url()).searchParams.get('archived') === 'true'
    archiveWrites.push(archived)
    await route.fulfill({ json: { ...saved, archived } })
  })
  const title = page.locator('.editor-content').getByRole('textbox', { name: 'Title', exact: true })
  await title.fill('Unsaved synthetic title')
  const archive = page.getByRole('button', { name: 'Archive', exact: true })
  await archive.click()
  const confirmation = page.getByRole('dialog', { name: 'Archive', exact: true })
  await expect(confirmation).toBeVisible()
  expect(archiveWrites).toEqual([])
  await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(confirmation).toHaveCount(0)
  expect(archiveWrites).toEqual([])
  await expect(title).toHaveValue('Unsaved synthetic title')

  await archive.click()
  await confirmation.getByRole('button', { name: 'Archive', exact: true }).click()
  const reactivate = page.getByRole('button', { name: 'Reactivate', exact: true })
  await expect(reactivate).toBeVisible()
  await expect(page.getByText('Archived', { exact: true })).toBeVisible()
  await expect(title).toHaveValue('Unsaved synthetic title')
  await page.screenshot({ path: test.info().outputPath('archived-process-actions.png'), fullPage: true, animations: 'disabled' })
  await reactivate.click()
  await expect(archive).toBeVisible()
  await expect(page.getByText('Archived', { exact: true })).toHaveCount(0)
  await expect(title).toHaveValue('Unsaved synthetic title')
  expect(archiveWrites).toEqual([true, false])
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].title).toBe('Unsaved synthetic title')
})

test('a process read-only grant keeps the definition visible without mutation controls', async ({ page }) => {
  const writes = await definitionFixtures(page, false)
  await mount(page, 'app/process/components/NativeProcessEditor.vue', { props: { code: 'invented_process' }, privileges: ['PROCESS_READ', 'PROCESS_EDIT'] })
  await expect(page.getByText('Read-only access', { exact: true })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Description', exact: true })).toHaveValue('Synthetic existing description')
  await expect(page.getByRole('textbox', { name: 'Description', exact: true })).not.toBeEditable()
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Task · work', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Task instructions', exact: true })).not.toBeEditable()
  await expect(page.getByRole('button', { name: 'Output of Start', exact: true })).toHaveCount(0)
  expect(writes).toEqual([])
})

for (const [host, width] of [['definition', 1440], ['definition', 390], ['tracking', 390], ['shared', 1440], ['chat', 1440], ['chat', 390]]) {
test(`internal run ${host} ${width}px view highlights active work and opens execution data without edits`, async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: async value => { window.copiedRunUrl = value } }, configurable: true,
  }))
  await page.setViewportSize({ width, height: 1000 })
  const value = graph()
  value.nodes[1].title = 'Synthetic running task'
  if (host === 'definition') { value.nodes[1].kind = 'call'; value.nodes[1].config = { process_code: 'synthetic_child' } }
  const active = { id: 'active-step', node_key: 'work', status: 'running', body_path: [], iteration: null,
    output: { integrated: 'synthetic data' }, started_at: '2026-01-01T12:00:00Z', finished_at: null }
  const previous = { ...active, id: 'previous-step', node_key: 'start', status: 'success', output: { previous: true } }
  const run = { id: 'synthetic-live-run', status: 'running', graph: value, definition_revision: 1, can_control: false,
    node_statuses: { start: 'success', work: 'running', end: 'queued' },
    data: { kept: false, result: 'Synthetic business value' },
    files: [{ uri: 'galaris://processes/runs/synthetic-live-run/attachments/11111111-1111-4111-8111-111111111111', filename: 'report.txt', content_type: 'text/plain', size: 25 }],
    data_revision: 1, data_uri: 'galaris://processes/runs/synthetic-live-run/data', attachments_uri: 'galaris://processes/runs/synthetic-live-run/attachments/', paused: false, breakpoints: [],
    output: null, error: null, error_code: null, parent_run_id: null, nodes: [previous], total: 55,
    page: 1, page_size: 50, event_cursor: 0, events: [], duration_seconds: 4, debugger_revision: 0,
    operational: { phase: 'running', last_activity_at: '2026-01-01T12:00:04Z',
      progress: { occurrences: 55, completed: 53, active: 1, ready: 1, failed: 0, cancelled: 0 },
      activities: [], activities_truncated: false, blocker: null, available_actions: [] } }
  const summary = { id: run.id, status: run.status, tool_code: 'galaris', process_id: 1, workflow_id: 'synthetic_flow',
    process_label: 'Synthetic inspection workflow', summary: 'Synthetic inspection workflow', input: {}, output: null,
    engine_metadata: {}, launcher_agent_id: 7, launcher_agent_code: 'synthetic_agent', created_at: '2026-01-01T12:00:00Z',
    started_at: '2026-01-01T12:00:00Z', finished_at: null, error_message: null, error_code: null, events: [], task_ids: [] }
  const accounting = { calls: 0, cost: 0.125, inference_cost: 0.5, tokens: null, estimated_calls: 0 }
  const mutations = []
  const unrelatedDownloads = []
  page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/processes/') && request.method() !== 'GET') mutations.push(request.method()) })
  await jsonRoute(page, '**/api/processes/internal/runs?**', { items: [{ id: run.id, status: run.status, process_label: summary.process_label, engine_code: 'galaris', result_preview: 'Synthetic execution result\nMore result details' }], total: 1, page: 1, page_size: 50 })
  await jsonRoute(page, '**/api/processes/internal/runs/synthetic-live-run?**', run)
  await page.route('**/api/processes/internal/runs/synthetic-live-run/files/*', route =>
    route.fulfill({ contentType: 'text/plain', body: 'Entirely synthetic report' }))
  await jsonRoute(page, '**/api/processes/internal/runs/synthetic-live-run/metrics', { direct: accounting, inclusive: { ...accounting, cost: 0.375 }, tasks: {}, nodes: {}, partial: true })
  let delayedMetrics
  if (host === 'shared') {
    let metricsFailed = false
    await page.route('**/api/processes/internal/runs/synthetic-live-run/metrics', route => {
      if (!metricsFailed) { metricsFailed = true; delayedMetrics = route; return }
      return route.fulfill({ json: { direct: accounting, inclusive: { ...accounting, cost: 0.375 }, tasks: {}, nodes: {}, partial: true } })
    })
  }
  await page.route('**/api/processes/internal/runs/synthetic-live-run/activities/*?**', route => {
    const url = new URL(route.request().url()), key = url.pathname.split('/').at(-1)
    expect(url.searchParams.get('page_size')).toBe('50')
    return route.fulfill({ json: { items: key === 'work' ? [active] : key === 'start' ? [previous] : [], total: key === 'end' ? 0 : 1, page: 1, page_size: 50 } })
  })
  await jsonRoute(page, '**/api/processes/internal/runs/synthetic-live-run/nodes/active-step', { ...active,
    attempts: [{ id: 'synthetic-attempt', number: 1, status: 'accepted', input: { amount: 42 }, prompt: 'Synthetic executed prompt',
      receipt: { output: { answer: 'synthetic task result' } }, task_uri: null,
      child_run_id: host === 'definition' ? 'synthetic-child-run' : null, error: null }] })
  let late
  await page.route('**/api/processes/internal/runs/synthetic-live-run/nodes/previous-step', route => { late = route })
  if (host === 'definition') {
    await mount(page, 'app/process/components/NativeRunsTable.vue', { props: { code: 'synthetic_flow' }, privileges: ['PROCESS_READ'] })
    await expect(page.getByText('Synthetic execution result', { exact: false })).toBeVisible()
    await test.info().attach('run-list', { body: await page.screenshot(), contentType: 'image/png' })
    const runLink = page.getByRole('link', { name: `Copy run URL: ${run.id}`, exact: true })
    await expect(runLink).toHaveAttribute('href', `galaris://processes/runs/${run.id}`)
    await runLink.click()
    await expect.poll(() => page.evaluate(() => window.copiedRunUrl)).toBe(`galaris://processes/runs/${run.id}`)
    await expect(page.getByRole('dialog')).toHaveCount(0)
    const row = page.getByLabel(`Show details: ${summary.process_label}`, { exact: true })
    if (width < 1024) { await row.focus(); await page.keyboard.press('Enter') }
    else await row.click()
  } else if (host === 'tracking') {
    await jsonRoute(page, '**/api/agents?*', [])
    await jsonRoute(page, '**/api/processes/runs?**', { items: [summary], total: 1, page: 1, page_size: 50 })
    await jsonRoute(page, '**/api/processes/runs/synthetic-live-run', summary)
    await jsonRoute(page, '**/api/processes/operations', { status_counts: { running: 1 }, pending_start_jobs: 0, stale_active_runs: 0, failed_last_24h: 0 })
    await mount(page, 'app/process/components/ProcessRunsPanel.vue', { privileges: ['PROCESS_READ'] })
    await page.locator('.process-active-run').click()
  } else if (host === 'chat') {
    await jsonRoute(page, '**/api/chat/rooms/synthetic-room/processes?**', { items: [summary], total: 1 })
    await mount(page, 'app/chat/components/ConversationProcessesPanel.vue', { props: {
      roomId: 'synthetic-room', fromMessageId: 'synthetic-message', canRead: true,
    }, privileges: ['PROCESS_READ'] })
    // A process remains usable even if another feature's screen cannot download.
    await page.route(/\/app\/(task|memory|voice|conversation)\/index\.ts(?:\?.*)?$/, route => { unrelatedDownloads.push(route) })
    await page.locator('.conversation-work-list').getByText(summary.process_label, { exact: true }).click()
  } else {
    await mount(page, 'app/process/components/NativeRunDialog.vue', { props: { runId: run.id, title: summary.process_label }, privileges: ['PROCESS_READ'] })
  }
  const work = page.getByRole('button', { name: 'Synthetic running task · work', exact: true })
  const openedAt = performance.now()
  await expect(work).toHaveAttribute('aria-current', 'step')
  if (host === 'chat') {
    await expect(page.getByRole('dialog').getByLabel('Elapsed time: 4 s', { exact: true })).toBeVisible()
    await expect(page.getByRole('dialog').getByLabel('Billed cost including children: $0.375', { exact: true })).toBeVisible()
  }
  if (host === 'shared') {
    // A slow accounting request must never hide the execution diagram.
    await expect.poll(() => Boolean(delayedMetrics)).toBe(true)
    test.info().annotations.push({ type: 'diagram-with-accounting-pending-ms', description: String(Math.round(performance.now() - openedAt)) })
    await delayedMetrics.fulfill({ status: 503, json: { detail: 'Synthetic metrics unavailable' } })
  }
  const runUrl = `galaris://processes/runs/${run.id}`
  {
    const reference = page.getByRole('dialog').getByRole('link', { name: `Copy run URL: ${run.id}`, exact: true })
    await expect(reference).toHaveAttribute('href', runUrl)
    await reference.focus()
    await page.keyboard.press('Enter')
  }
  await expect.poll(() => page.evaluate(() => window.copiedRunUrl)).toBe(runUrl)
  if (host === 'shared') {
    const error = page.getByRole('alert').filter({ has: page.getByRole('button', { name: 'Retry', exact: true }) })
    await expect(error).toBeVisible()
    await error.getByRole('button', { name: 'Retry', exact: true }).click()
    await expect(error).toHaveCount(0)
    const data = page.getByRole('textbox', { name: 'Run data', exact: true })
    await expect(data).toHaveValue(JSON.stringify(run.data, null, 2))
    await expect(data).toHaveAttribute('readonly', '')
    await expect(page.getByText('report.txt', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Add attachments', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Remove report.txt', exact: true })).toHaveCount(0)
    await page.locator('.document-attachments .resource-preview-main').click()
    const preview = page.getByRole('dialog', { name: 'Open preview of report.txt', exact: true })
    await expect(preview).toContainText('Entirely synthetic report')
    await preview.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(preview).toHaveCount(0)
    await page.locator('.document-attachments__item').hover()
    const pendingDownload = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Download report.txt', exact: true }).click()
    expect((await pendingDownload).suggestedFilename()).toBe('report.txt')
    await page.screenshot({ path: test.info().outputPath('run-data-and-files.png'), animations: 'disabled' })
  }
  await work.click()
  const inspector = page.getByRole('dialog', { name: 'Activity execution', exact: true })
  await expect(inspector.getByRole('textbox', { name: 'Input data', exact: true })).toHaveValue(/42/)
  await expect(inspector.getByRole('textbox', { name: 'Output data', exact: true })).toHaveValue(/synthetic data/)
  await expect(inspector.getByRole('textbox', { name: 'Task or operation result', exact: true })).toHaveValue(/synthetic task result/)
  expect(await inspector.locator('textarea').evaluateAll(fields => fields.every(field => field.readOnly))).toBe(true)
  await page.screenshot({ path: test.info().outputPath('run-diagram-execution-details.png'), animations: 'disabled' })
  await page.getByRole('button', { name: 'Start · start', exact: true }).click()
  await expect.poll(() => Boolean(late)).toBe(true)
  await page.getByRole('button', { name: 'End · end', exact: true }).click()
  await expect(inspector).toContainText('This activity has not run yet.')
  const delivered = page.waitForResponse(response => response.url().includes('/nodes/previous-step'))
  await late.fulfill({ json: { ...previous, output: { obsolete: 'Discard this late activity result' }, attempts: [] } })
  await delivered
  await expect(inspector).not.toContainText('Discard this late activity result')
  await expect(inspector).toContainText('This activity has not run yet.')
  await inspector.getByRole('button', { name: 'Close execution details', exact: true }).click()
  if (host === 'shared') {
    run.status = 'success'; run.node_statuses.work = 'success'
    await expect(work).not.toHaveAttribute('aria-current', 'step')
  }
  if (host === 'definition') {
    await work.click()
    await inspector.getByRole('link', { name: 'Open child process', exact: true }).click()
    await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/process/internal/run/synthetic-child-run')
    await expect(work).toHaveCount(0)
  } else if (host !== 'shared') {
    const modal = page.getByRole('dialog').filter({ has: work })
    await modal.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(work).toHaveCount(0)
    if (host === 'chat') {
      await page.locator('.conversation-work-list').getByText(summary.process_label, { exact: true }).click()
      await expect(work).toBeVisible()
      await page.getByRole('dialog').filter({ has: work }).getByRole('button', { name: 'Close', exact: true }).click()
      await expect(work).toHaveCount(0)
    }
  }
  expect(mutations).toEqual([])
  expect(unrelatedDownloads).toEqual([])
})
}

test('live run events refresh the diagram and open results without losing in-flight updates', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-01-01T12:00:00Z') })
  await page.clock.pauseAt(new Date('2026-01-01T12:01:00Z'))
  const active = { id: 'live-step', node_key: 'work', status: 'running', body_path: [], iteration: null,
    output: { progress: 'Initial synthetic result' }, started_at: '2026-01-01T12:00:00Z', finished_at: null, attempts: [] }
  const run = { id: 'event-run', status: 'running', graph: graph(), can_control: false,
    node_statuses: { work: 'running' }, data: {}, files: [], data_revision: 1, data_uri: "", attachments_uri: "", paused: false, breakpoints: [],
    output: null, error: null, parent_run_id: null, nodes: [active], total: 1,
    page: 1, page_size: 50, event_cursor: 0, events: [], duration_seconds: 3 }
  let reads = 0, pendingRun, pendingNode, holdNextRun = false
  await page.route('**/api/processes/internal/runs/event-run?*', route => {
    reads++
    if (holdNextRun) { holdNextRun = false; pendingRun = route; return }
    return route.fulfill({ json: run })
  })
  const accounting = { calls: 0, cost: null, tokens: null, estimated_calls: 0 }
  let pendingMetrics, metricsReads = 0
  await page.route('**/api/processes/internal/runs/event-run/metrics', route => {
    if (++metricsReads === 1) { pendingMetrics = route; return }
    return route.fulfill({ json: { direct: accounting, inclusive: accounting, tasks: {}, nodes: {}, partial: true } })
  })
  await page.route('**/api/processes/internal/runs/event-run/activities/work?*', route =>
    route.fulfill({ json: { items: [active], total: 1, page: 1, page_size: 50 } }))
  let details = 0
  await page.route('**/api/processes/internal/runs/event-run/nodes/live-step', route => {
    if (++details === 1) { pendingNode = route; return }
    return route.fulfill({ json: active })
  })
  await mount(page, 'resourceDetails.vue', { props: { target: { kind: 'process_run', id: run.id, title: 'Synthetic live process' } }, privileges: ['PROCESS_READ'] })
  const work = page.getByRole('button', { name: 'Task · work', exact: true })
  await expect(work).toHaveAttribute('aria-current', 'step')
  await page.clock.runFor(500)
  await work.click()
  await expect.poll(() => Boolean(pendingNode)).toBe(true)
  const baseline = reads
  await page.evaluate(() => window.testApp.emitSocket('process_run.update', { data: { id: 'another-run' } }))
  await page.clock.runFor(150)
  expect(reads).toBe(baseline)
  holdNextRun = true
  await page.evaluate(() => window.testApp.emitSocket('process_run.update', { data: { id: 'event-run' } }))
  await page.clock.runFor(150)
  await expect.poll(() => Boolean(pendingRun)).toBe(true)
  const staleRun = structuredClone(run), staleNode = structuredClone(active)
  run.status = 'success'; run.node_statuses.work = 'success'
  active.status = 'success'; active.output = { progress: 'Final synthetic result' }
  run.duration_seconds = 8; accounting.cost = 0.25
  await page.evaluate(async () => {
    for (let i = 0; i < 4; i++) await window.testApp.emitSocket('process_run.update', { data: { id: 'event-run' } })
  })
  await page.clock.runFor(150)
  expect(reads).toBe(baseline + 1)
  await pendingRun.fulfill({ json: staleRun })
  await expect.poll(() => reads).toBe(baseline + 2)
  await expect(work).not.toHaveAttribute('aria-current', 'step')
  await pendingNode.fulfill({ json: staleNode })
  const inspector = page.getByRole('dialog', { name: 'Activity execution', exact: true })
  await expect(inspector.getByRole('textbox', { name: 'Output data', exact: true })).toHaveValue(/Final synthetic result/)
  expect(metricsReads).toBe(1)
  await pendingMetrics.fulfill({ json: { direct: accounting, inclusive: accounting, tasks: {}, nodes: {}, partial: true } })
  await expect.poll(() => metricsReads).toBe(2)
  await expect(page.getByLabel('Elapsed time: 8 s', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Billed cost including children: $0.25', { exact: true })).toBeVisible()
  await page.evaluate(() => window.testApp.emitSocket('connect'))
  await expect.poll(() => reads).toBe(baseline + 3)
  // Terminal runs also catch up after reconnect; closing detaches the subscriber.
  await page.evaluate(() => window.testApp.unmount())
  await page.evaluate(() => window.testApp.emitSocket('process_run.update', { data: { id: 'event-run' } }))
  await page.clock.runFor(5000)
  expect(reads).toBe(baseline + 3)
})

test('live run navigation discards a late response from the previous run', async ({ page }) => {
  let pending, pendingMetrics
  await page.route('**/api/processes/internal/runs/old-run?*', route => { pending = route })
  const fresh = { id: 'new-run', status: 'success', graph: graph(), definition_revision: 1,
    can_control: true, node_statuses: { work: 'success' }, data: {}, files: [], data_revision: 1, data_uri: "", attachments_uri: "", paused: false,
    breakpoints: [], output: { synthetic: true }, error: null, parent_run_id: null,
    nodes: [], total: 0, page: 1, page_size: 50, event_cursor: 0, events: [], duration_seconds: 3 }
  fresh.graph.nodes[1].title = 'Fresh synthetic result'
  const accounting = { calls: 0, cost: null, tokens: null, estimated_calls: 0 }
  await jsonRoute(page, '**/api/processes/internal/runs/*/metrics', { direct: accounting, inclusive: accounting, tasks: {}, nodes: {}, partial: true })
  await page.route('**/api/processes/internal/runs/old-run/metrics', route => { pendingMetrics = route })
  await jsonRoute(page, '**/api/processes/internal/runs/new-run?*', fresh)
  await mount(page, 'app/process/components/NativeRunPanel.vue', { props: { runId: 'old-run' }, privileges: ['PROCESS_READ', 'PROCESS_LAUNCH'] })
  await expect.poll(() => Boolean(pending)).toBe(true)
  await page.evaluate(() => window.testApp.setProps({ runId: 'new-run' }))
  await expect(page.getByRole('button', { name: 'Fresh synthetic result · work', exact: true })).toBeVisible()
  const late = page.waitForResponse(response => response.url().includes('/old-run?'))
  await pending.fulfill({ json: { ...fresh, id: 'old-run', status: 'error', error: 'Obsolete synthetic failure' } })
  await late
  await expect.poll(() => Boolean(pendingMetrics)).toBe(true)
  const lateMetrics = page.waitForResponse(response => response.url().endsWith('/old-run/metrics'))
  await pendingMetrics.fulfill({ json: { direct: { ...accounting, cost: 9876.54 }, inclusive: accounting, tasks: {}, nodes: {}, partial: false } })
  await lateMetrics
  await expect(page.getByText('Obsolete synthetic failure', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Direct billed cost: Unavailable', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Pause admissions', exact: true })).toHaveCount(0)
  await expect(page.getByText('Accounting is partial', { exact: true })).toBeVisible()
})

test('retrying a debugger command after a lost reply retains its admission identity', async ({ page }) => {
  let revision = 0
  const commands = []
  await page.route('**/api/processes/internal/runs/debug-run?*', route => route.fulfill({ json: {
    id: 'debug-run', status: 'running', graph: graph(), can_control: true, node_statuses: {},
    data: {}, files: [], data_revision: 1, data_uri: "", attachments_uri: "", paused: true, breakpoints: [], output: null, error: null, parent_run_id: null,
    nodes: [], total: 0, page: 1, page_size: 50, event_cursor: 0, events: [], duration_seconds: 3,
    debugger_revision: revision,
  } }))
  const accounting = { calls: 0, cost: null, tokens: null, estimated_calls: 0 }
  await jsonRoute(page, '**/api/processes/internal/runs/debug-run/metrics', { direct: accounting, inclusive: accounting, tasks: {}, nodes: {}, partial: true })
  await page.route('**/api/processes/internal/runs/debug-run/control', async route => {
    commands.push(route.request().postDataJSON())
    if (commands.length === 1) { revision = 1; return route.abort('failed') }
    return route.fulfill({ json: { debugger_revision: revision } })
  })
  await mount(page, 'app/process/components/NativeRunPanel.vue', { props: { runId: 'debug-run' }, privileges: ['PROCESS_READ', 'PROCESS_LAUNCH'] })
  const step = page.getByRole('button', { name: 'Step', exact: true })
  await step.click()
  await expect.poll(() => commands.length).toBe(1)
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await expect(step).toBeEnabled()
  await step.click()
  await expect.poll(() => commands.length).toBe(2)
  expect(commands[1]).toEqual(commands[0])
  expect(commands[0]).toMatchObject({ action: 'step', expected_revision: 0 })
  expect(commands[0].command_key).toMatch(/^[0-9a-f-]{36}$/)
})

test('run progress explains messaging waits and controls the same run through confirmed stop', async ({ page }) => {
  let paused = false, stopped = false, allowed = true
  const commands = []
  await page.route('**/api/processes/internal/runs/observed-run?*', route => route.fulfill({ json: {
    id: 'observed-run', status: stopped ? 'cancelled' : 'running', graph: graph(), can_control: allowed,
    node_statuses: {}, data: {}, files: [], data_revision: 1, data_uri: "", attachments_uri: "", paused, breakpoints: [], output: null, error: null,
    parent_run_id: null, nodes: [], total: 0, page: 1, page_size: 50, event_cursor: 0, events: [], debugger_revision: commands.length,
    operational: { phase: stopped ? 'cancelled' : paused ? 'paused' : 'waiting', last_activity_at: '2026-01-01T12:00:00Z',
      progress: { completed: 1, active: stopped ? 0 : 1, ready: 0, failed: 0 },
      activities: stopped ? [] : [{ kind: 'human_reply', occurrence_id: 'invented-occurrence', node_key: 'work', body_path: [], question: 'Which synthetic document should be used?' }],
      available_actions: !allowed || stopped ? [] : paused ? ['resume', 'cancel'] : ['pause', 'cancel'], blocker: null },
  } }))
  const accounting = { calls: 0, cost: null, tokens: null, estimated_calls: 0 }
  await jsonRoute(page, '**/api/processes/internal/runs/observed-run/metrics', { direct: accounting, inclusive: accounting, tasks: {}, nodes: {}, partial: false })
  await page.route('**/api/processes/internal/runs/observed-run/control', async route => {
    const command = route.request().postDataJSON(); commands.push(command.action); paused = command.action === 'pause'
    await route.fulfill({ json: {} })
  })
  await page.route('**/api/processes/internal/runs/observed-run/cancel', async route => {
    commands.push('cancel'); stopped = true; await route.fulfill({ json: {} })
  })
  await mount(page, 'app/process/components/NativeRunPanel.vue', { props: { runId: 'observed-run' }, privileges: ['PROCESS_READ', 'PROCESS_LAUNCH'] })
  await expect(page.getByText('Waiting for a reply in messaging', { exact: true })).toBeVisible()
  await expect(page.getByText('Which synthetic document should be used?', { exact: true })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('waiting-process-progress.png'), fullPage: true, animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: test.info().outputPath('waiting-process-progress-mobile.png'), fullPage: true, animations: 'disabled' })
  await page.getByRole('button', { name: 'Pause admissions', exact: true }).click()
  await expect(page.getByText(/New activities are paused/)).toBeVisible()
  await page.getByRole('button', { name: 'Resume', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Pause admissions', exact: true })).toBeVisible()
  expect(commands).toEqual(['pause', 'resume'])
  allowed = false
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Stop run', exact: true })).toHaveCount(0)
  await expect(page.getByText('Which synthetic document should be used?', { exact: true })).toBeVisible()
  allowed = true
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await page.getByRole('button', { name: 'Stop run', exact: true }).click()
  const confirmation = page.getByRole('dialog', { name: 'Stop run', exact: true })
  await expect(confirmation).toBeVisible()
  expect(commands).toEqual(['pause', 'resume'])
  await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(confirmation).toHaveCount(0)
  expect(commands).toEqual(['pause', 'resume'])
  await page.getByRole('button', { name: 'Stop run', exact: true }).click()
  await confirmation.getByRole('button', { name: 'Stop run', exact: true }).click()
  await expect(page.getByText('Stopped', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Resume', exact: true })).toHaveCount(0)
  await expect(page.getByText('Which synthetic document should be used?', { exact: true })).toHaveCount(0)
  expect(commands).toEqual(['pause', 'resume', 'cancel'])
  await page.screenshot({ path: test.info().outputPath('stopped-process-progress.png'), fullPage: true, animations: 'disabled' })
})
