import { test, expect, mount } from './fixtures.mjs'

const component = 'core/util/components/RichTextEditor.vue'
const documentId = '00000000-0000-0000-0000-000000000001'
const uri = `document://${documentId}/attachments/00000000-0000-0000-0000-000000000002`
const file = name => ({ name, mimeType: 'text/plain', buffer: Buffer.from('attachment') })

async function setup(page) {
  await mount(page, component)
  await page.evaluate(async ({ component, uri }) => {
    window.uploads = []
    await window.testApp.mount({ component, props: {
      profile: 'document', modelValue: '<p>Before</p><p>After</p>',
      uploadFile: (file, signal, progress) => new Promise(resolve => {
        progress(.5)
        window.uploads.push({ name: file.name, signal, finish: () => resolve(uri) })
      }),
    } })
  }, { component, uri })
  await page.locator('.ck-editor__editable p').first().click()
  await page.keyboard.press('Home')
  await page.keyboard.press('End')
}

async function drop(page, files) {
  const payload = (Array.isArray(files) ? files : [files]).map(file => ({
    name: file.name, type: file.mimeType, content: file.buffer.toString(),
  }))
  await page.locator('.ck-editor__editable').evaluate((root, files) => {
    const box = root.querySelector('p:first-child').getBoundingClientRect()
    const data = new DataTransfer()
    for (const file of files) data.items.add(new File([file.content], file.name, { type: file.type }))
    root.dispatchEvent(new DragEvent('drop', {
      bubbles: true, cancelable: true, dataTransfer: data,
      clientX: box.x + box.width - 5, clientY: box.y + box.height / 2,
    }))
  }, payload)
}

test('dropped files retain their insertion point while typing elsewhere and keep file order', async ({ page }) => {
  await setup(page)
  await drop(page, [file('first.txt'), file('second.txt')])
  await expect(page.getByRole('status')).toContainText('first.txt · 50% · 1/2')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.locator('.ck-editor__editable p').last().click()
  await page.keyboard.press('End')
  await page.keyboard.type(' edited')
  await page.evaluate(() => window.uploads[0].finish())
  await expect(page.getByRole('status')).toContainText('second.txt')
  await page.evaluate(() => window.uploads[1].finish())
  await expect(page.getByRole('status')).toHaveCount(0)
  const content = page.locator('.ck-editor__editable')
  await expect(content).toContainText('first.txt')
  await expect(content).toContainText('second.txt')
  const html = await content.innerHTML()
  expect(html.indexOf('Before')).toBeLessThan(html.indexOf('first.txt'))
  expect(html.indexOf('first.txt')).toBeLessThan(html.indexOf('second.txt'))
  expect(html.indexOf('second.txt')).toBeLessThan(html.indexOf('After edited'))
  await expect(content.locator('blockquote')).toHaveCount(2)
  await page.keyboard.type(' still here')
  await expect(content.locator('p').last()).toContainText('After edited still here')
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1).value)).toContain(uri)
})

test('a mixed image and file selection retains its order', async ({ page }) => {
  await setup(page)
  const image = { name: 'first.png', mimeType: 'image/png', buffer: Buffer.from('image fixture') }
  await drop(page, [image, file('second.txt')])
  await expect(page.getByRole('status')).toContainText('first.png')
  await page.evaluate(() => window.uploads[0].finish())
  await expect(page.getByRole('status')).toContainText('second.txt')
  await page.evaluate(() => window.uploads[1].finish())
  await expect(page.getByRole('status')).toHaveCount(0)
  const html = await page.locator('.ck-editor__editable').innerHTML()
  expect(html.indexOf('first.png')).toBeLessThan(html.indexOf('second.txt'))
  expect(html.indexOf('second.txt')).toBeLessThan(html.indexOf('After'))
})

for (const action of ['cancel', 'switch', 'readonly']) test(`${action} discards a late upload result`, async ({ page }) => {
  await setup(page)
  await drop(page, file('late.txt'))
  await expect(page.getByRole('status')).toContainText('late.txt')
  if (action === 'cancel') await page.getByRole('button', { name: 'Cancel upload', exact: true }).click()
  if (action === 'switch') await page.evaluate(() => window.testApp.setProps({ modelValue: '<p>Another document</p>' }))
  if (action === 'readonly') await page.evaluate(() => window.testApp.setProps({ readonly: true }))
  await expect.poll(() => page.evaluate(() => window.uploads[0].signal.aborted)).toBe(true)
  await page.evaluate(() => window.uploads[0].finish())
  await expect(page.getByRole('status')).toHaveCount(0)
  await expect(page.locator('.ck-editor__editable')).not.toContainText('late.txt')
  if (action === 'readonly') {
    await drop(page, file('blocked.txt'))
    expect(await page.evaluate(() => window.uploads.length)).toBe(1)
    await expect(page.locator('.ck-editor__editable')).not.toContainText('blocked.txt')
  }
})

test('dropping a file uses the drop location rather than the old cursor position', async ({ page }) => {
  await setup(page)
  await page.locator('.ck-editor__editable').evaluate(root => {
    const target = root.querySelector('p:last-child')
    const box = target.getBoundingClientRect()
    const data = new DataTransfer()
    data.items.add(new File(['attachment'], 'drop.txt', { type: 'text/plain' }))
    root.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: data, clientX: box.x + box.width - 5, clientY: box.y + box.height / 2 }))
  })
  await expect(page.getByRole('status')).toContainText('drop.txt')
  await page.evaluate(() => window.uploads[0].finish())
  const html = await page.locator('.ck-editor__editable').innerHTML()
  expect(html.indexOf('After')).toBeLessThan(html.indexOf('drop.txt'))
})
