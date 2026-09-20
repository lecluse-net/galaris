import { test, expect, mount } from './fixtures.mjs'

for (const dark of [false, true]) test(`thumbnail proportions fill the available dimension without a background in ${dark ? 'dark' : 'light'} mode`, async ({ page }, testInfo) => {
  await mount(page, 'core/util/components/ResourcePreviewBlock.vue', {
    dark, containerStyle: { width: 'min(480px, 100vw)' },
    props: { placement: 'below-page', title: 'Portrait', subtitle: '99 ko', openLabel: 'Open image' },
  })
  for (const [name, width, height] of [['portrait', 213, 320], ['landscape', 520, 260], ['square', 320, 320], ['transparent', 40, 20]]) {
    await page.evaluate(async ({ name, width, height }) => {
      const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height
      const context = canvas.getContext('2d')
      context.fillStyle = '#0866ed'
      if (name === 'transparent') context.fillRect(width / 4, height / 4, width / 2, height / 2)
      else context.fillRect(0, 0, width, height)
      await window.testApp.setProps({ title: name, image: canvas.toDataURL('image/png') })
    }, { name, width, height })
    const card = page.locator('.resource-preview-card'), visual = card.locator('.resource-preview-visual'), image = visual.locator('img')
    await expect(image).toHaveJSProperty('naturalWidth', width)
    await expect(image).toHaveJSProperty('naturalHeight', height)
    await expect(image).toHaveCSS('object-fit', 'contain')
    await expect(visual).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)')
    await expect(image).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)')
    const box = await image.boundingBox(), area = await visual.boundingBox()
    expect(box.width).toBeCloseTo(area.width, 0)
    expect(box.height).toBeCloseTo(area.height, 0)
    await card.screenshot({ path: testInfo.outputPath(`${name}.png`) })
  }
})
