export interface HarnessBrand {
  providerCode: string
  label: string
  logo: string
  icon: string
  accent: string
  accentSecondary: string
}

interface HarnessBrandModule {
  default: HarnessBrand
}

const bridgeBrandModules = import.meta.glob<HarnessBrandModule>(
  '../../bridge/*/harnessBrand.ts',
  { eager: true },
)

const bridgeBrands = Object.values(bridgeBrandModules).map(module => module.default)

const applicationBrands: HarnessBrand[] = [
  {
    providerCode: 'openai_messages',
    label: 'OpenAI Messages',
    logo: '/harness-logos/messages-api.svg',
    icon: 'img:/harness-logos/messages-api.svg',
    accent: '#06b6d4',
    accentSecondary: '#4f46e5',
  },
  {
    providerCode: 'internal',
    label: 'Galaris',
    logo: '/logo/256.png',
    icon: 'img:/logo/256.png',
    accent: '#1976d2',
    accentSecondary: '#7c3aed',
  },
]

const brands = new Map(
  [...bridgeBrands, ...applicationBrands].map(brand => [brand.providerCode, brand]),
)

const fallback: HarnessBrand = {
  providerCode: 'unknown',
  label: 'Harness',
  logo: '/logo/256.png',
  icon: 'img:/logo/256.png',
  accent: '#1976d2',
  accentSecondary: '#7c3aed',
}

export function harnessBrand(providerCode: string): HarnessBrand {
  return brands.get(providerCode) ?? fallback
}

export function builtinHarnessBrands(): HarnessBrand[] {
  return [...bridgeBrands]
}
