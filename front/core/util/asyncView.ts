import { defineAsyncComponent, defineComponent, h, shallowRef, type AsyncComponentLoader, type Component } from 'vue'
import AsyncViewState from './components/AsyncViewState.vue'

/** Share the loaded view, but let a failed download retry without losing page state. */
export function defineAsyncView<T extends Component>(loader: AsyncComponentLoader<T>): T {
  const retryLoad = shallowRef<(() => void) | null>(null)
  return defineAsyncComponent<T>({
    loader,
    delay: 120,
    loadingComponent: defineComponent({
      setup: () => () => h(AsyncViewState, {
        failed: retryLoad.value !== null,
        onRetry: () => {
          const retry = retryLoad.value
          retryLoad.value = null
          retry?.()
        },
      }),
    }),
    // Keep the download pending until the user retries. Vue forwards slots and
    // current props; exposed methods are available only on the resolved view,
    // not on the temporary loading component assigned to a template ref.
    onError: (_error, retry) => { retryLoad.value = retry },
  })
}
