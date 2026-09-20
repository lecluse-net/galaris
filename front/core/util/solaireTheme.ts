import { solaireStyles } from './solaire'

export { solaireCss } from './solaire'

// Imported by the public utility surface and direct editor integrations.
// Updating the source palette refreshes this stylesheet through Vite's HMR.
if (typeof document !== 'undefined') {
  const existing = document.getElementById('galaris-solaire-palette')
  const style = existing ?? document.createElement('style')
  style.id = 'galaris-solaire-palette'
  style.textContent = solaireStyles
  if (!existing) document.head.append(style)
}
