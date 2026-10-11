/** Network access notice contributed by an external service. */
export interface NetworkAccessRequirement {
  kind: string
  label: string
  mode: 'outbound' | 'public-https' | 'reverse-websocket'
  hintKey: string
  warningKey?: string
}

/** Recognize local addresses from their spelling; this does not resolve DNS. */
export function isPrivateHostname(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, '').replace(/\.$/, '')
  if (!host || !host.includes('.') && !host.includes(':')) return true
  if (/(^|\.)(localhost|local|lan|home|internal|intranet|private|test|invalid|example)$/.test(host)
      || host === 'home.arpa' || host.endsWith('.home.arpa')) return true

  const ipv4 = host.split('.').map(Number)
  if (/^\d+\.\d+\.\d+\.\d+$/.test(host) && ipv4.every(part => part >= 0 && part <= 255)) {
    const [a, b] = ipv4
    return a === 0 || a === 10 || a === 127
      || a === 169 && b === 254
      || a === 172 && b! >= 16 && b! <= 31
      || a === 192 && b === 168
      || a === 100 && b! >= 64 && b! <= 127
      || a! >= 224
  }

  if (host.includes(':')) {
    // URL normalizes IPv6, including IPv4-mapped addresses, into hexadecimal.
    let normalized: string
    try { normalized = new URL(`http://[${host}]/`).hostname.slice(1, -1) }
    catch { return true }
    if (normalized === '::' || normalized === '::1'
        || /^(fc|fd|fe[89ab]|ff)/.test(normalized)) return true
    const mapped = normalized.match(/^::ffff:([\da-f]+):([\da-f]+)$/)
    if (mapped) {
      const high = parseInt(mapped[1]!, 16)
      const low = parseInt(mapped[2]!, 16)
      return isPrivateHostname(`${high >> 8}.${high & 255}.${low >> 8}.${low & 255}`)
    }
  }
  return false
}
