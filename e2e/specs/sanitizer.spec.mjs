import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import { test, expect } from '@playwright/test'

const moduleUrl = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64')
const resourceModule = moduleUrl(stripTypeScriptTypes(readFileSync('/front/core/util/resourceUri.ts', 'utf8')))
const source = moduleUrl(stripTypeScriptTypes(readFileSync('/front/core/util/sanitizeHtml.ts', 'utf8'))
  .replace("from './resourceUri'", `from '${resourceModule}'`))

test('rich HTML sanitizer removes active protocols and preserves ordinary content in a real DOM', async ({ page }) => {
  await page.addScriptTag({ type: 'module', content: `import { sanitizeHtml } from '${source}'; window.sanitize = sanitizeHtml;` })
  await page.waitForFunction(() => typeof window.sanitize === 'function')
  const result = await page.evaluate(() => {
    const payload = '<p>Text <strong>bold</strong></p>'
      + '<a href="java&#x09;script:alert(1)">tab</a>'
      + '<a href="&#10;JaVaScRiPt:alert(1)">case</a>'
      + '<a href="vbscript:bad">vb</a><a href="data:text/html,bad">data</a>'
      + '<a href="/documents?id=1">document</a>'
      + '<img src="https://example.test/image.png" onerror="alert(1)" srcset="javascript:bad">'
      + '<svg><a href="javascript:bad">svg</a></svg>'
      + '<form action="https://evil.test"><input name="token"></form>'
      + '<div id="location" onclick="alert(1)">safe</div>'
    const host = document.createElement('div')
    host.innerHTML = window.sanitize(payload)
    return {
      active: [...host.querySelectorAll('a[href]')].map(a => a.getAttribute('href')),
      dangerous: host.querySelectorAll('svg, form, input, [onclick], [onerror], [srcset], [id]').length,
      text: host.textContent,
      image: host.querySelector('img').getAttribute('src'),
    }
  })
  expect(result.active).toEqual(['/documents?id=1'])
  expect(result.dangerous).toBe(0)
  expect(result.text).toContain('Text bold')
  expect(result.image).toBe('https://example.test/image.png')
})
