import { randomUUID } from 'node:crypto'
import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

// Exercise the assembled shell and real APIs: a domain must not fetch its
// neighbour's administrative catalogue merely to display existing records.
const cases = [
  ['AGENT_ACCESS', '/agent'], ['AGENT_EDIT', '/agent'],
  ['TASK_PURGE', '/params/logs'], ['LLM_CALL_PURGE', '/params/logs'], ['INCIDENT_PURGE', '/params/logs'],
  ['CHAT_ACCESS', '/chat'], ['CHAT_SEND', '/chat', ['CHAT_ACCESS']], ['CHAT_MANAGE', '/chat', ['CHAT_ACCESS']],
  ['CHAT_CALL', '/chat', ['CHAT_ACCESS']], ['CHAT_IMPERSONATE', '/chat', ['CHAT_ACCESS']],
  ...[
    ['CONTACT', '/memory/contacts'], ['MEMORY', '/memory'],
    ['DOCUMENT', '/documents'], ['FILE', '/files'],
    ['GOAL', '/goal'], ['GOAL_CONFIG', '/goal'], ['SKILL', '/skill'],
    ['TOPIC', '/topic'], ['TASK', '/task?tab=tasks'],
    ['LLM_PROVIDER', '/llm?tab=providers'], ['LLM_MODEL', '/llm?tab=models'],
    ['LLM_PROFILE', '/llm?tab=profiles'], ['TOOL', '/tools?tab=tools'],
    ['CONNECTION', '/tools?tab=connections'], ['MAIL', '/connection/mail'],
    ['CALENDAR', '/connection/calendars'],
  ].flatMap(([prefix, path]) => ['ACCESS', 'EDIT'].map(suffix => [`${prefix}_${suffix}`, path])),
  ['DATASET_READ', '/dataset'], ['DATASET_EDIT', '/dataset'],
  ['PROCESS_READ', '/process'], ['PROCESS_EDIT', '/process'],
  ['FILE_INDEX_ACCESS', '/params/files'], ['FILE_INDEX_RUN', '/params/files'],
  ['CONVERSATION_ACCESS', '/task?tab=conversations'], ['CONVERSATION_CONTROL', '/task?tab=conversations'],
  ['VOICE_HISTORY_ACCESS', '/task?tab=voice'], ['VOICE_HISTORY_CONTROL', '/task?tab=voice'],
  ['LLM_CALL_ACCESS', '/task?tab=llm'], ['LLM_CALL_CONTROL', '/task?tab=llm'],
  ['PERMISSION_ACCESS', '/permissions'], ['PERMISSION_DECIDE', '/permissions'],
  ['DASHBOARD_ACCESS', '/dashboard'],
  ...[
    ['PARAMS', 'system'], ['LANGUAGE_CONFIG', 'language'], ['MESSAGING_CONFIG', 'messaging'],
    ['MEMORY_CONFIG', 'memory'], ['VOICE_CONFIG', 'voice'], ['AUDIO_CONFIG', 'audio'],
    ['PROCESS_CONFIG', 'processes'], ['TASK_CONFIG', 'tasks'], ['SEARCH_CONFIG', 'search'],
    ['JANUS_CONFIG', 'janus'], ['INSTRUCTION_CONFIG', 'instructions'], ['LOG_CONFIG', 'logs'],
    ['HARNESS_CONFIG', 'harnesses'],
  ].flatMap(([prefix, slug]) => ['ACCESS', 'EDIT'].map(suffix => [`${prefix}_${suffix}`, `/params/${slug}`])),
  ['DREAM_CONFIG_ACCESS', '/params/dream'], ['DREAM_EDIT', '/params/dream'],
  ['DREAM_ACCESS', '/dream', ['AGENT_MANAGE_ALL']],
  ['BROWSER_CONFIG_ACCESS', '/browser/settings'], ['BROWSER_CONFIG_EDIT', '/browser/settings'],
  ['DOCUMENT_ADMIN', '/documents'], ['DATASET_ADMIN', '/dataset'], ['MEMORY_ADMIN', '/memory'],
  ['PROCESS_ADMIN', '/process'], ['SKILL_ASSIGN', '/skill'], ['PERMISSION_REVOKE', '/permissions'],
  ['INCIDENT_ACCESS', '/incident'], ['INCIDENT_EDIT', '/incident'],
  ...['READ_USER', 'CREATE_USER', 'UPDATE_USER', 'DELETE_USER'].map(code => [code, '/user/users']),
  ...['READ_ROLE', 'MANAGE_ROLE', 'READ_PRIVILEGE', 'MANAGE_PRIVILEGE', 'READ_ASSIGNMENT', 'MANAGE_ASSIGNMENT'].map(code => [code, '/authorize']),
  ['TEAM_ACCESS', '/team'], ['TEAM_EDIT', '/team', ['TEAM_ACCESS']], ['TEAM_MEMBERS_EDIT', '/team', ['TEAM_ACCESS']],
  ...[
    ['EVALUATION', 'ai-evaluations'], ['PROCESS_EVALUATION', 'processes'],
    ['DISPATCHER_EVALUATION', 'dispatcher'], ['PLANNER_EVALUATION', 'planner'],
    ['TOPIC_CLASSIFICATION_EVALUATION', 'topic-detection'], ['MEMORY_EXTRACTION_EVALUATION', 'memory-extraction'],
    ['OUTCOME_REFLECTION_EVALUATION', 'learning'], ['GOAL_TRACKING_EVALUATION', 'goal-tracking'],
    ['TASK_EXECUTOR_EVALUATION', 'task-executor'], ['CONVERSATION_EXECUTOR_EVALUATION', 'conversation-executor'],
    ['VOICE_EXECUTOR_EVALUATION', 'voice-executor'],
  ].flatMap(([prefix, slug]) => ['ACCESS', 'EDIT'].map(suffix => [`${prefix}_${suffix}`, `/lab/${slug}`])),
]

let credentials
const roles = new Map()
const checked = async response => {
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

test.beforeAll(async ({ request }) => {
  const fixture = await checked(await request.post('/api/__test/seed'))
  const session = await checked(await request.post('/api/auth/login-json', { data: { email: fixture.email, password: fixture.password } }))
  const headers = { Authorization: `Bearer ${session.access_token}`, 'X-Editorial-Profile-Version': '1' }
  const suffix = randomUUID()
  credentials = { email: `synthetic-domains-${suffix}@example.com`, password: 'Synthetic-domains-123!' }
  const user = await checked(await request.post('/api/auth/users', { headers, data: { ...credentials, language: 'en' } }))
  const catalogue = await checked(await request.get('/api/authorize/privileges', { headers }))
  for (const [code, , extra = []] of cases) {
    const privilege = catalogue.find(item => item.code === code)
    expect(privilege, code).toBeTruthy()
    const role = await checked(await request.post('/api/authorize/roles', { headers, data: { code: `domain-${suffix}-${code}` } }))
    await checked(await request.post(`/api/authorize/roles/${role.id}/privileges`, { headers, data: { privilege_ids: [privilege.id, ...extra.map(code => catalogue.find(item => item.code === code).id)] } }))
    await checked(await request.post('/api/authorize/assignments', { headers, data: { user_id: user.id, role_id: role.id, is_default: roles.size === 0 } }))
    roles.set(code, role.id)
  }
  const owner = await checked(await request.get(`/api/agents/${fixture.agent_id}`, { headers }))
  await checked(await request.post('/api/agents', { headers, data: { user_id: user.id, title_id: owner.title_id,
    code: `domain-${suffix}`, first_name: 'Synthetic', last_name: 'Domain operator' } }))
})

for (const [code, path] of cases) test(`${code} opens its function without neighbouring privileges`, async ({ page }) => {
  const session = await checked(await page.request.post('/api/auth/login-json', { data: credentials }))
  const active = await checked(await page.request.post('/api/authorize/switch-role', {
    headers: { Authorization: `Bearer ${session.access_token}` }, data: { role_id: roles.get(code) },
  }))
  await page.addInitScript(token => localStorage.setItem('access_token', token), active.access_token)
  const errors = collectPageErrors(page)
  const failures = []
  page.on('response', response => {
    const pathname = new URL(response.url()).pathname
    if (pathname.startsWith('/api/') && response.status() >= 400 && pathname !== '/api/auth/refresh') failures.push(`${response.status()} ${pathname}`)
  })
  await page.goto(path)
  await expect(page.locator('.q-page')).toBeVisible()
  await expect(page).toHaveURL(new RegExp(new URL(path, 'http://test').pathname.replaceAll('/', '\\/')))
  await errors.settle()
  expect(failures).toEqual([])
  expect(errors()).toEqual([])
})
