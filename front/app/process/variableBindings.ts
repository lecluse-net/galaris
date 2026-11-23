import type { BpmnGraph, BpmnNode, NodeKind, ProcessVariable } from './services/nativeProcessService'

export type VariableDirection = 'inputs' | 'outputs'
export interface VariableConsumer { key: string; path: string[]; node: BpmnNode }

const inputReferences = { human_prompt_variable: 'string', correlation_variable: 'string', date_variable: 'datetime' } as const

export function allowsVariableDirection(kind: NodeKind, direction: VariableDirection): boolean {
  return direction === 'inputs' ? !['end', 'event_choice', 'error_boundary'].includes(kind)
    : !['start', 'if', 'timer', 'event_wait', 'event_choice', 'error_boundary'].includes(kind)
}

export function withVariableBindings(node: BpmnNode, direction: VariableDirection, values: string[]): BpmnNode {
  const config = { ...node.config }
  if (direction === 'inputs') for (const key of Object.keys(inputReferences)) {
    const value = config[key]
    if (typeof value !== 'string' || values.includes(value)) continue
    if (key === 'date_variable') config[key] = null
    else delete config[key]
  }
  return { ...node, [direction]: values, config }
}

export function processInputs(graph: BpmnGraph): string[] {
  return graph.nodes.find(node => node.kind === 'start')?.inputs ?? []
}

export function processOutputs(graph: BpmnGraph): string[] {
  return [...new Set(graph.nodes.filter(node => node.kind === 'end').flatMap(node => node.outputs ?? []))]
}

export function variableConsumers(graph: BpmnGraph): VariableConsumer[] {
  const consumers: VariableConsumer[] = []
  function visit(body: BpmnGraph, path: string[]): void {
    for (const node of body.nodes) {
      const location = [...path, node.id]
      consumers.push({ key: JSON.stringify(location), path: location, node })
      if (node.body) visit(node.body, location)
    }
  }
  visit(graph, [])
  return consumers
}

export function variableUsage(graph: BpmnGraph, name: string, direction: VariableDirection): string[] {
  return variableConsumers(graph).filter(consumer => allowsVariableDirection(consumer.node.kind, direction)
    && (consumer.node[direction] ?? []).includes(name)).map(consumer => consumer.key)
}

export function setVariableUsage(graph: BpmnGraph, name: string, direction: VariableDirection, keys: string[]): BpmnGraph {
  if (!graph.variables?.some(variable => variable.name === name)) return graph
  function visit(body: BpmnGraph, path: string[]): BpmnGraph {
    const nodes = body.nodes.map(node => {
      const location = [...path, node.id], names = node[direction] ?? []
      const selected = allowsVariableDirection(node.kind, direction) && keys.includes(JSON.stringify(location))
      const values = selected ? names.includes(name) ? names : [...names, name] : names.filter(value => value !== name)
      return { ...withVariableBindings(node, direction, values),
        body: node.body ? visit(node.body, location) : null }
    })
    return { ...body, nodes }
  }
  return visit(graph, [])
}

export function updateProcessVariables(graph: BpmnGraph, variables: ProcessVariable[]): BpmnGraph {
  const previous = graph.variables ?? []
  const renamed = previous.length === variables.length && previous.filter((variable, index) => variable.name !== variables[index]?.name).length === 1
    ? previous.findIndex((variable, index) => variable.name !== variables[index]?.name) : -1
  const names = new Set(variables.map(variable => variable.name))
  function references(values: string[] = []): string[] {
    return [...new Set(values.map(value => renamed >= 0 && value === previous[renamed]!.name ? variables[renamed]!.name : value).filter(value => names.has(value)))]
  }
  function visit(body: BpmnGraph): BpmnGraph {
    return { ...body, nodes: body.nodes.map(node => {
      const config = { ...node.config }
      for (const [key, type] of Object.entries(inputReferences)) {
        const value = config[key]
        if (typeof value !== 'string') continue
        const [name] = references([value])
        if (variables.some(variable => variable.name === name && variable.type === type)) config[key] = name
        else if (key === 'date_variable') config[key] = null
        else delete config[key]
      }
      return { ...node, config, inputs: references(node.inputs), outputs: references(node.outputs),
        body: node.body ? visit(node.body) : null }
    }) }
  }
  return { ...visit(graph), variables }
}
