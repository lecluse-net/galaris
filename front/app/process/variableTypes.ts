export const mimeTypes = [
  ['image/*', 'images'], ['audio/*', 'audio'], ['video/*', 'video'], ['text/*', 'texts'],
  ['application/pdf', 'pdf'], ['text/plain', 'plain'], ['text/html', 'html'], ['text/markdown', 'markdown'],
  ['application/json', 'json'], ['text/csv', 'csv'], ['application/xml', 'xml'],
  ['application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'docx'],
  ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'xlsx'],
  ['application/vnd.openxmlformats-officedocument.presentationml.presentation', 'pptx'],
  ['application/vnd.oasis.opendocument.text', 'odt'], ['application/vnd.oasis.opendocument.spreadsheet', 'ods'],
  ['image/png', 'png'], ['image/jpeg', 'jpeg'], ['image/webp', 'webp'], ['image/gif', 'gif'], ['image/svg+xml', 'svg'],
  ['audio/mpeg', 'mp3'], ['audio/wav', 'wav'], ['audio/ogg', 'ogg'], ['video/mp4', 'mp4'], ['video/webm', 'webm'],
  ['application/zip', 'zip'], ['application/octet-stream', 'binary'],
] as const
export const mimeTypePattern = /^[a-z0-9!#$&^_.+-]+\/(?:[a-z0-9!#$&^_.+-]+|\*)$/
export const integerReferenceTypes = ['Agent', 'User', 'Team', 'Tool', 'Connection', 'Model', 'Skill']
export const hiddenValueTypes = ['VoiceSession', 'VoiceConversation', 'GoalCycle', 'ProcessRun', 'Memory', 'ConversationRound']
