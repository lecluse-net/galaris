import { Dialog, type QBtnProps } from 'quasar'
import ConfirmationDialog from './components/ConfirmationDialog.vue'

export interface ConfirmationDialogOptions {
  title?: string
  message: string
  ok?: boolean | string | QBtnProps
  cancel?: boolean | string | QBtnProps
  color?: string
  flatActions?: boolean
}

/** Keep Quasar's outcome callbacks while sharing the application's title bar. */
export function showConfirmationDialog(options: ConfirmationDialogOptions) {
  const dialog = Dialog.create({ component: ConfirmationDialog, componentProps: options })
  const chain = {
    ...dialog,
    onOk(callback: (value?: unknown) => void | Promise<void>) {
      dialog.onOk((value?: unknown) => {
        // Quasar does not observe a callback's returned promise.
        try { void Promise.resolve(callback(value)).catch(error => console.error('Confirmation action failed', error)) }
        catch (error) { console.error('Confirmation action failed', error) }
      })
      return chain
    },
  }
  return chain
}
