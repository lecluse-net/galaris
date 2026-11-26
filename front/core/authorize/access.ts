export let privilegeCatalogueEnabled = false

export function configurePrivilegeCatalogue(isDevelopment: boolean): void {
  privilegeCatalogueEnabled = isDevelopment
}
