import type { CapabilityDefinition, Tool } from './services/toolService'

export function capabilityCode(value: string): string {
  return value.slice(value.lastIndexOf('.') + 1)
}

export function toolCapabilitySelections(tool: Partial<Tool>): string[] {
  if (tool.capabilities) return [...tool.capabilities]
  const result: string[] = []
  if (tool.mcp_config) result.push(`${tool.mcp_config.type}.mcp`)
  if (tool.rest_config) result.push('rest.api')
  if (tool.file_share_config) result.push(`${tool.file_share_config.service}.file_share`)
  if (tool.messenger_config) result.push(`${tool.messenger_config.service}.messenger`)
  if (tool.listener_config) result.push('webhook.listener')
  if (tool.has_mail) result.push('imap_smtp.mail')
  if (tool.has_calendar) result.push('caldav.calendar')
  return result
}

type Translate = (key: string, values?: Record<string, string>) => string

export function capabilityLabels(value: string, definitions: CapabilityDefinition[], t: Translate): {
  capability: string; protocol: string; label: string
} {
  const definition = definitions.find(item => item.code === capabilityCode(value))
  const protocol = definition?.protocols.find(item => item.value === value)
  if (!definition) return { capability: value, protocol: value, label: value }
  const capability = definition.builtin ? t(definition.label) : definition.label
  if (!protocol) return { capability, protocol: value, label: value }
  const protocolLabel = protocol.builtin ? t(protocol.label) : protocol.label
  return { capability, protocol: protocolLabel,
    label: t('tools.capabilityProtocol', { capability, protocol: protocolLabel }) }
}
