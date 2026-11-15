import { test, expect, mount, setPrivileges } from './fixtures.mjs'

test('tab titles follow navigation, nested pages, language and current privileges', async ({ page }) => {
  await mount(page, 'test-support/browser/PageTitleHarness.vue', {
    route: '/documents', privileges: ['DOCUMENT_ACCESS', 'TASK_ACCESS'],
  })
  await expect(page).toHaveTitle('Documents')
  await page.evaluate(() => window.testApp.setProps({ title: 'Synthetic folder' }))
  await expect(page).toHaveTitle('Synthetic folder')
  await page.evaluate(() => window.testApp.setProps({ title: 'Renamed synthetic folder' }))
  await expect(page).toHaveTitle('Renamed synthetic folder')
  await page.evaluate(() => window.testApp.setProps({ title: undefined }))
  await expect(page).toHaveTitle('Documents')
  await page.evaluate(() => window.testApp.navigate('/task'))
  await expect(page).toHaveTitle('Activity')
  await page.evaluate(async () => { const { setLocale } = await import('/core/i18n/index.ts'); await setLocale('fr') })
  await expect(page).toHaveTitle('Activité')
  await page.evaluate(() => window.testApp.navigate('/documents/folders/synthetic-folder'))
  await expect(page).toHaveTitle('Documents')
  await page.evaluate(() => window.testApp.navigate('/documents-other'))
  await expect(page).toHaveTitle('Galaris')
  await page.evaluate(() => window.testApp.navigate('/task'))
  await expect(page).toHaveTitle('Activité')
  await setPrivileges(page, [])
  await expect(page).toHaveTitle('Galaris')
})
