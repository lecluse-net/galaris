import { useMeta } from 'quasar'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useNavigation } from './useNavigation'

/** Use the existing translated navigation labels for browser and desktop tabs. */
export function usePageTitle(): void {
  const route = useRoute()
  const { t } = useI18n()
  const { flatNodes } = useNavigation()

  useMeta(() => {
    const page = flatNodes.value
      .filter(node => node.to && node.label && (node.to === route.path || (node.to !== '/' && route.path.startsWith(`${node.to}/`))))
      .sort((left, right) => (right.to?.length ?? 0) - (left.to?.length ?? 0))[0]
    return page?.label ? { title: t(page.label) } : {}
  })
}
