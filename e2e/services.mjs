import { expect } from '@playwright/test'

export async function openCustomService(page) {
  await page.getByRole('button', { name: 'Nouveau service', exact: true }).click()
  await page.getByRole('button', { name: 'Créer un service personnalisé', exact: true }).click()
}

export async function addServiceProtocol(page, protocol) {
  await page.getByRole('dialog').getByRole('button', { name: 'Ajouter un protocole', exact: true }).click()
  await page.getByRole('menu', { name: 'Ajouter un protocole', exact: true }).getByRole('menuitem', { name: protocol, exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('tab', { name: protocol, exact: true })).toBeVisible()
}
