import { expect } from '@playwright/test'

export async function selectOption(page, combobox, label) {
  if (await combobox.inputValue() === label) return
  await expect(combobox).toBeVisible()
  // Quasar's selected-value layer can cover its native readonly input.
  await combobox.press('ArrowDown')
  await expect(combobox).toHaveAttribute('aria-expanded', 'true')
  const openLists = page.getByRole('listbox')
  await expect(openLists).toHaveCount(1)
  const listId = await openLists.getAttribute('id')
  expect(listId).toBeTruthy()
  const list = page.locator(`[id=${JSON.stringify(listId)}]`)
  await expect(list.getByRole('option').first()).toBeVisible()
  // A virtual list moving under a parked pointer can change its keyboard focus.
  await page.mouse.move(0, 0)
  const option = list.getByRole('option', { name: label, exact: true })
  // Page through the real virtual list. Typeahead retains its previous query
  // across rapid reopenings, so a second label can leave the wrong row focused.
  await combobox.press('Home')
  await expect.poll(async () => {
    if (await option.isVisible()) return true
    const previous = await combobox.getAttribute('aria-activedescendant')
    await combobox.press('PageDown')
    if (await combobox.getAttribute('aria-activedescendant') === previous) await combobox.press('Home')
    return option.isVisible()
  }, { intervals: [50] }).toBe(true)
  await option.click()
  await expect(combobox).toHaveValue(label)
  await expect(list).toBeHidden()
}
