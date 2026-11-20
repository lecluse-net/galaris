/** Shared structural contracts; visual layout is verified in the assembled shell. */
export const uiConventions = {
  meta: { type: 'problem', schema: [], messages: {
    labeledFlat: 'Labeled actions use native filled or outline QBtn styling.',
    missingName: 'Icon actions require an accessible label or forwarded attributes.',
    dialogDismissal: 'Dialogs must allow backdrop dismissal.',
    confirmationFocus: 'Confirmation dialogs require a single primary QBtn with data-autofocus.',
    deletion: 'Labeled deletion actions use the native filled negative style.',
    color: 'Outlined labeled actions require an explicit color.',
    palette: 'Use a Solaire color or a configured semantic/neutral color.',
  } },
  create(context) {
    const services = context.sourceCode.parserServices
    if (!services.defineTemplateBodyVisitor) return {}
    return services.defineTemplateBodyVisitor({ VElement(node) {
      const props = node.startTag.attributes
      const property = name => props.find(prop => !prop.directive && prop.key.name === name
        || prop.directive && prop.key.name.name === 'bind' && prop.key.argument?.name === name)
      const constant = prop => prop && !prop.directive ? prop.value?.value ?? true : undefined
      const report = (messageId, prop) => context.report({ node: prop ?? node.startTag, messageId })
      if (node.rawName === 'q-dialog') {
        for (const name of ['persistent', 'no-backdrop-dismiss']) if (property(name)) report('dialogDismissal', property(name))
        if (property('data-confirmation')) {
          const targets = []
          const visit = element => {
            if (element.type !== 'VElement' || element.rawName === 'q-dialog') return
            if (element.startTag.attributes.some(attr => {
              const name = attr.directive && attr.key.name.name === 'bind' ? attr.key.argument?.name : attr.key.name
              return name === 'data-autofocus' || name === 'autofocus'
            })) targets.push(element)
            element.children.forEach(visit)
          }
          node.children.forEach(visit)
          if (property('no-focus') || targets.length !== 1 || targets[0].rawName !== 'q-btn'
            || !targets[0].startTag.attributes.some(attr => !attr.directive && attr.key.name === 'data-autofocus')) report('confirmationFocus')
        }
      }
      if (node.rawName === 'q-btn') {
        const labeled = property('label')
        if (labeled && property('flat')) report('labeledFlat', property('flat'))
        if (labeled && constant(property('color')) === 'negative' && (property('outline') || property('flat'))) report('deletion')
        if (labeled && property('outline') && !property('color') && !property('style')) report('color')
        if (property('icon') && !labeled && !property('aria-label') && !property('title')
          && !props.some(prop => prop.directive && prop.key.name.name === 'bind' && !prop.key.argument)) report('missingName')
      }
      if (node.rawName.startsWith('q-')) for (const name of ['color', 'text-color']) {
        const prop = property(name), value = constant(prop)
        if (typeof value === 'string' && /^(?:deep-orange|deep-purple|light-blue|light-green|blue-grey|blue|green|yellow|red|purple|indigo|pink|orange|cyan|teal|amber|lime|brown)(?:-\d+)?$/.test(value)) report('palette', prop)
      }
    } })
  },
}
