import ChatProfilePreferences from './components/ChatProfilePreferences.vue'
import ChatIdentityMappings from './components/ChatIdentityMappings.vue'

export default {
  component: ChatProfilePreferences,
  identityComponent: ChatIdentityMappings,
  order: 40,
  privilege: 'CHAT_ACCESS',
}
