import { settings } from '@/core/settings'
import { solaireCss } from '@/core/util'

const editions = {
  dev: { color: solaireCss.orange.accent, badgeColor: solaireCss.orange.dark, label: 'index.environment.dev' },
  test: { color: solaireCss.iris.accent, badgeColor: solaireCss.iris.dark, label: 'index.environment.test' },
  pp: { color: solaireCss.fuchsia.accent, badgeColor: solaireCss.fuchsia.dark, label: 'index.environment.pp' },
  demo: { color: solaireCss.cyan.accent, badgeColor: solaireCss.cyan.dark, label: 'index.environment.demo' },
} as const

const edition = Object.hasOwn(editions, settings.APP_ENV)
  ? editions[settings.APP_ENV as keyof typeof editions]
  : undefined

export const environmentLabel = edition?.label
export const environmentBadgeColor = edition?.badgeColor
const tint = edition ? `color-mix(in srgb, ${edition.color} 75%, transparent)` : undefined
export const environmentStyle = edition
  ? {
      background: `linear-gradient(${tint}, ${tint}), url('/background.jpg') center`,
      backgroundColor: edition.color,
      color: '#ffffff',
    }
  : undefined
