import { test, expect, mount } from './fixtures.mjs'

const customBlue = {
  accent: 'rgb(31, 73, 101)',
  light: 'rgb(231, 239, 243)',
  dark: 'rgb(21, 33, 41)',
}

async function changeBlue(page) {
  await page.evaluate(palette => {
    for (const [variant, value] of Object.entries(palette)) {
      document.documentElement.style.setProperty(`--solaire-blue-${variant}`, value)
    }
  }, customBlue)
}

test('one global palette update reaches Preferences and Lab in both themes', async ({ page }) => {
  await mount(page, 'core/params/components/PreferencesMenuGrid.vue', {
    privileges: ['DISPATCHER_EVALUATION_ACCESS'],
    props: { items: [{ key: 'preview', title: 'Theme preview', description: 'Shared palette', icon: 'settings', to: '/params', color: 'blue' }] },
  })
  const registered = await page.evaluate(async () => {
    const { solaire } = await import('/core/util/solaire.ts')
    const styles = getComputedStyle(document.documentElement)
    return Object.entries(solaire).every(([color, shades]) => (
      Object.entries(shades).every(([variant, value]) => (
        styles.getPropertyValue(`--solaire-${color}-${variant}`).trim() === value
      ))
    ))
  })
  expect(registered).toBe(true)
  await changeBlue(page)
  const preferences = page.locator('.preferences-menu-grid__card')
  await expect(preferences).toHaveCSS('background-color', customBlue.light)
  await expect.poll(() => preferences.evaluate(node => getComputedStyle(node, '::before').backgroundColor)).toBe(customBlue.accent)
  await page.evaluate(() => window.testApp.dark(true))
  await expect(preferences).toHaveCSS('background-color', customBlue.dark)

  // Keep the document and its overridden palette while switching real screens.
  await page.evaluate(() => window.testApp.mount({ component: 'app/lab/pages/index.vue', route: '/lab' }))
  await page.evaluate(() => window.testApp.dark(false))
  const lab = page.locator('.lab-home__card')
  await expect(lab).toHaveCount(1)
  await expect(lab).toHaveCSS('background-color', customBlue.light)
  await page.evaluate(() => window.testApp.dark(true))
  await expect(lab).toHaveCSS('background-color', customBlue.dark)

})

test('folder artwork and highlighted code follow global tokens without regenerating assets', async ({ page }) => {
  await mount(page, 'core/util/components/FolderIcon.vue', { props: { tone: 'blue' } })
  await changeBlue(page)
  const folder = page.locator('.galaris-folder-icon')
  await expect(folder.locator('path').first()).toHaveCSS('fill', customBlue.accent)
  await page.evaluate(() => window.testApp.setProps({ expanded: true }))
  await expect(folder.locator('path').first()).toHaveCSS('fill', customBlue.accent)

  await page.evaluate(() => window.testApp.mount({
    component: 'core/util/components/RichText.vue',
    props: { content: '<pre><code class="language-javascript">const answer = 42;</code></pre>' },
  }))
  const keyword = page.locator('.hljs-keyword').first()
  await expect(keyword).toHaveText('const')
  await page.evaluate(accent => {
    document.documentElement.style.setProperty('--solaire-violet-accent', accent)
    document.documentElement.style.setProperty('--solaire-red-accent', accent)
  }, customBlue.accent)
  await expect(keyword).toHaveCSS('color', customBlue.accent)
  await page.evaluate(() => window.testApp.dark(true))
  await expect(keyword).toHaveCSS('color', customBlue.accent)
})
