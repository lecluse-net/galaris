/** Approved application palette: docs/fr/dev/palette-solaire.md (decision 0081). */
export const solaire = {
  yellow: { accent: '#FFE610', light: '#FFF4DE', dark: '#383517' },
  orange: { accent: '#FF9A00', light: '#FFF7EB', dark: '#382A15' },
  salmon: { accent: '#FA8072', light: '#FFF5F4', dark: '#382725' },
  red: { accent: '#F43636', light: '#FEEFEF', dark: '#371C1C' },
  fuchsia: { accent: '#D936B5', light: '#FCEFF9', dark: '#331C2E' },
  violet: { accent: '#AD3CE6', light: '#F8EFFD', dark: '#2D1D35' },
  iris: { accent: '#854CF0', light: '#F5F1FE', dark: '#271F36' },
  blue: { accent: '#087FF5', light: '#EBF5FE', dark: '#162637' },
  cyan: { accent: '#00B8D4', light: '#EBF9FC', dark: '#152E32' },
  green: { accent: '#11A653', light: '#ECF8F1', dark: '#172C20' },
  gray: { accent: '#808080', light: '#F5F5F5', dark: '#272727' },
} as const

export type SolaireColor = keyof typeof solaire
export const solaireColors = Object.keys(solaire) as SolaireColor[]

type SolaireVariants = Record<keyof typeof solaire.blue, string>

/** CSS references for live UI colours; literal values above are for exports. */
export const solaireCss = Object.fromEntries(solaireColors.map(color => [color, {
  accent: `var(--solaire-${color}-accent)`,
  light: `var(--solaire-${color}-light)`,
  dark: `var(--solaire-${color}-dark)`,
}])) as Record<SolaireColor, SolaireVariants>

/** Generated from the same source for the application and standalone documents. */
export const solaireStyles = `:root {\n${solaireColors.flatMap(color => (
  Object.entries(solaire[color]).map(([variant, value]) => `  --solaire-${color}-${variant}: ${value};`)
)).join('\n')}\n}`
