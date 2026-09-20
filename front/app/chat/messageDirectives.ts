const VISIBLE_TASK_CONTROL_DIRECTIVE_RE = /(?<![\p{L}\p{N}_])@(?:task|eff(?:ort)?)(?=$|[^\p{L}\p{N}_])(?:[ \t]+)?/giu

/** Keep Task controls in the posted message while hiding them from Chat projections. */
export function visibleMessageText(value: string): string {
  return value.replace(VISIBLE_TASK_CONTROL_DIRECTIVE_RE, '').trim()
}
