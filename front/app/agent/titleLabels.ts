/** Only built-in civilities are keys; administrator-defined labels remain literal. */
export function titleLabel(label: string, translate: (key: string) => string): string {
  return label === 'agent_titles.mr' || label === 'agent_titles.ms'
    ? translate(label)
    : label
}
