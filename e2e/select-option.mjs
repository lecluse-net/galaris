import { expect } from '@playwright/test'

export async function selectOption(page, combobox, label) {
  if (await combobox.inputValue() === label) return
  await combobox.click()
  await expect(combobox).toHaveAttribute('aria-expanded', 'true')
  const list = page.getByRole('listbox')
  await expect(list.getByRole('option').first()).toBeVisible()
  // Native keyboard search avoids clicking a recycled virtual row. The
  // committed value proves the choice even when its row is outside the DOM.
  await combobox.pressSequentially(label)
  await combobox.press('Enter')
  await expect(combobox).toHaveValue(label)
}
