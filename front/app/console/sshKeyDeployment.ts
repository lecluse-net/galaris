function shellSingleQuote(value: string): string {
  return `'${value.replaceAll("'", `'"'"'`)}'`
}

export function authorizedKeysDeploymentCommands(publicKey: string): string {
  const normalizedKey = publicKey.trim()
  if (!normalizedKey) return ''

  const quotedKey = shellSingleQuote(normalizedKey)
  return [
    'mkdir -p ~/.ssh',
    'chmod 700 ~/.ssh',
    'touch ~/.ssh/authorized_keys',
    'chmod 600 ~/.ssh/authorized_keys',
    `grep -qxF -- ${quotedKey} ~/.ssh/authorized_keys || printf '%s\\n' ${quotedKey} >> ~/.ssh/authorized_keys`,
  ].join('\n')
}
