/** Validate stored references without resolving providers or granting access. */
const protocols = new Set('about blob cid coap coaps dav dns ftp ftps git http https imap ipfs ipns javascript ldap ldaps magnet mailto nfs nntp pop rtmp rtsp sftp smb smtp ssh svn tel telnet urn ws wss workspace processus agent connection conversation goal process round task tool'.split(' '))
const uuid = '[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'
const identity = new RegExp(`^${uuid}$`)
const document = new RegExp(`^(?:${uuid}(?:/attachments/(?:${uuid})?)?|folders/(?:${uuid}/?)?)$`)
const hasControl = (value: string): boolean => [...value].some(char => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)

export function canonicalResourceLink(value: string): boolean {
  const match = /^([a-z][a-z0-9+.-]*):\/\/(.*)$/.exec(value)
  if (!match || protocols.has(match[1]!)) return false
  const scheme = match[1]!, locator = match[2]!
  if (/[\s\\?#]/u.test(locator) || hasControl(locator)) return false
  try {
    const decoded = decodeURIComponent(locator)
    if (hasControl(decoded)) return false
    const segments = decoded.split('/')
    if (segments.some((part, index) => part === '.' || part === '..' || !part && index < segments.length - 1)) return false
    const canonical = segments.map(part => encodeURIComponent(part.normalize('NFC')).replace(/%(?:24|26|2B|2C|3B|3D|40|3A)/gi, code => decodeURIComponent(code))).join('/')
    if (canonical !== locator) return false
    if (!locator) return true
    if (scheme === 'file' || scheme === 'memory') return identity.test(locator)
    if (scheme === 'document' || scheme === 'data') return (scheme === 'document' || !locator.startsWith('folders/')) && document.test(locator)
    return true
  } catch { return false }
}
