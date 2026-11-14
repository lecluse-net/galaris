import TelegramServiceSetup from './components/TelegramServiceSetup.vue'
import MatrixServiceSetup from './components/MatrixServiceSetup.vue'

// Service creation belongs to this domain; bridge settings provide the setup guide.
export const messagingSetupComponents = { telegram: TelegramServiceSetup, matrix: MatrixServiceSetup }
