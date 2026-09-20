// Exercise the actual Playwright collector: ordinary tests run; focused tests fail.
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'

const root = mkdtempSync('/tests/focus-gate-')
try {
  for (const [name, source] of [['e2e', '/tests/playwright.config.mjs'], ['components', '/component-config.mjs']]) {
    const directory = join(root, name)
    mkdirSync(join(directory, 'specs'), { recursive: true })
    const config = join(directory, 'playwright.config.mjs')
    writeFileSync(config, readFileSync(source))
    const spec = join(directory, name === 'e2e' ? 'specs/probe.spec.mjs' : 'probe.spec.mjs')
    for (const focused of [false, true]) {
      writeFileSync(spec, `import { test } from '@playwright/test'\ntest${focused ? '.only' : ''}('collector probe', async () => {})\n`)
      const result = spawnSync(process.execPath, ['/tests/node_modules/@playwright/test/cli.js', 'test', '--config', config, '--reporter=line'], { encoding: 'utf8', timeout: 30000 })
      const output = result.stdout + result.stderr
      if (result.error || result.status !== (focused ? 1 : 0) || (focused && !output.includes('forbidOnly'))) {
        throw new Error(`${name}: ${focused ? 'focused' : 'ordinary'} test gate failed\n${output}`)
      }
    }
    console.log(`${name}: ordinary test accepted, test.only rejected`)
  }
} finally {
  rmSync(root, { recursive: true, force: true })
}
