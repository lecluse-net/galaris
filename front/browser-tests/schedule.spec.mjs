import { test, expect, mount } from './fixtures.mjs'

async function editor(page, allowedSlots = ['0:8', '0:9', '1:8']) {
  await mount(page, 'app/goal/components/GoalScheduleEditor.vue', {
    props: { enabled: true, slots: [], allowedSlots, showEnabledToggle: false },
    setProps: ['slots', 'allowedSlots'],
  })
}
const slot = (page, weekday, hour) => page.locator(`[data-schedule-slot][data-weekday="${weekday}"][data-hour="${hour}"]`)

test('schedule keyboard and group actions respect the global allowed slots', async ({ page }) => {
  await editor(page)
  await expect(page.getByRole('checkbox')).toHaveCount(168)
  await slot(page, 0, 8).press('Space')
  await expect(slot(page, 0, 8)).toHaveAttribute('aria-checked', 'true')
  await slot(page, 0, 7).click({ force: true })
  await expect(slot(page, 0, 7)).toHaveAttribute('aria-checked', 'false')
  await expect(slot(page, 0, 7)).toHaveAttribute('aria-disabled', 'true')
  await page.locator('[data-schedule-group="weekday"][data-group-index="0"]').click()
  await expect(page.locator('[data-weekday="0"][aria-checked="true"]')).toHaveCount(2)
  await page.locator('[data-schedule-group="hour"][data-group-index="8"]').click()
  await expect(slot(page, 1, 8)).toHaveAttribute('aria-checked', 'true')
  await expect(slot(page, 2, 8)).toHaveAttribute('aria-checked', 'false')
  await page.getByRole('button', { name: 'Disable all' }).click()
  await expect(page.locator('[data-schedule-slot][aria-checked="true"]')).toHaveCount(0)
})

test('schedule pointer drag paints once per slot and stops on release', async ({ page }) => {
  await editor(page)
  const a = await slot(page, 0, 8).boundingBox()
  const b = await slot(page, 1, 8).boundingBox()
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2)
  await page.mouse.down()
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 5 })
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2, { steps: 5 })
  await page.mouse.up()
  await expect(slot(page, 0, 8)).toHaveAttribute('aria-checked', 'true')
  await expect(slot(page, 1, 8)).toHaveAttribute('aria-checked', 'true')
  await slot(page, 0, 9).hover()
  await expect(slot(page, 0, 9)).toHaveAttribute('aria-checked', 'false')
})

test('a schedule can be selected and cleared on mobile without enabling forbidden hours', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await editor(page)
  await slot(page, 0, 8).click()
  await expect(slot(page, 0, 8)).toHaveAttribute('aria-checked', 'true')
  await expect(slot(page, 0, 7)).toHaveAttribute('aria-disabled', 'true')
  await page.getByRole('button', { name: 'Disable all' }).click()
  await expect(page.locator('[data-schedule-slot][aria-checked="true"]')).toHaveCount(0)
})
