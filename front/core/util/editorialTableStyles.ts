export const tablePalettes = ['blue', 'iris', 'green', 'orange', 'salmon', 'gray'] as const
export const tableTreatments = ['contrast', 'striped', 'minimal'] as const
export type TablePalette = typeof tablePalettes[number]
export type TableTreatment = typeof tableTreatments[number]
export const tableStyleClasses = [...tablePalettes, ...tableTreatments].map(value => `galaris-table-${value}`)

/** Replace only the preset, retaining column widths and other authored attributes. */
export function withTableStyle(classes: string | null, palette?: TablePalette, treatment?: TableTreatment): string | null {
  const retained = (classes ?? '').split(/\s+/).filter(value => value && !tableStyleClasses.includes(value))
  if (palette && treatment) retained.push(`galaris-table-${palette}`, `galaris-table-${treatment}`)
  return retained.join(' ') || null
}
