import { onBeforeUnmount, ref } from 'vue'
import { isAxiosError } from 'axios'

export interface CaptureMismatch {
  code: 'dataset_parameters_mismatch'
  dataset_name: string
  confirmation_token: string
  differences: Array<{ name: string; source_value: unknown; dataset_value: unknown }>
}

/** A retry is sent only after explicit confirmation of the current differences. */
export function useCaptureConfirmation() {
  const mismatch = ref<CaptureMismatch | null>(null)
  let active = true
  let resolve: ((confirmed: boolean) => void) | undefined
  function finish(confirmed: boolean) {
    mismatch.value = null
    resolve?.(confirmed)
    resolve = undefined
  }
  onBeforeUnmount(() => { active = false; finish(false) })
  async function run<T>(capture: (token?: string) => Promise<T>): Promise<T | null> {
    let token: string | undefined
    for (;;) {
      if (!active) return null
      try { return await capture(token) }
      catch (error) {
        if (!active) return null
        if (!isAxiosError<{ detail: CaptureMismatch }>(error) || error.response?.status !== 409 || error.response.data.detail?.code !== 'dataset_parameters_mismatch') throw error
        const detail = error.response.data.detail
        const confirmed = await new Promise<boolean>(done => { resolve = done; mismatch.value = detail })
        if (!confirmed) return null
        token = detail.confirmation_token
      }
    }
  }
  return { mismatch, run, confirm: () => finish(true), cancel: () => finish(false) }
}
