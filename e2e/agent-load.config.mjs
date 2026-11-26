import config from './playwright.config.mjs'

export default { ...config, testDir: './load', timeout: 600_000,
  projects: config.projects.filter(project => project.name === 'chromium'),
  use: { ...config.use, trace: 'off' } }
