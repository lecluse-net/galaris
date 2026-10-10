// Screen-sized marker and link quads keep the existing two node sizes while
// supporting the 2D graph's SVGs, outlines and per-relation CSS pixel widths.
export const markerVertexShader = `
  attribute vec3 center;
  attribute vec3 tint;
  attribute vec3 appearance;
  attribute vec4 border;
  attribute vec2 glyph;
  attribute float borderWidth;
  uniform vec2 viewport;
  varying vec2 local;
  varying vec3 color;
  varying vec2 style;
  varying vec4 outline;
  varying vec2 icon;
  varying vec2 edge;
  void main() {
    vec4 clip = projectionMatrix * vec4(mat3(viewMatrix) * center, 1.0);
    clip.xy += position.xy * appearance.x * 2.0 / viewport * clip.w;
    gl_Position = clip;
    local = position.xy * 2.0;
    color = tint;
    style = appearance.yz;
    outline = border;
    icon = glyph;
    edge = vec2(borderWidth, appearance.x);
  }
`

export const markerFragmentShader = `
  uniform sampler2D glyphAtlas;
  varying vec2 local;
  varying vec3 color;
  varying vec2 style;
  varying vec4 outline;
  varying vec2 icon;
  varying vec2 edge;
  vec4 artwork(vec2 uv) {
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) return vec4(0.0);
    return texture2D(glyphAtlas, vec2(mod(icon.x, 8.0) + uv.x, 7.0 - floor(icon.x / 8.0) + uv.y) / 8.0);
  }
  void main() {
    if (style.x > 2.5) {
      vec2 uv = (local + 1.0) * 0.5;
      vec4 texel = artwork(uv);
      float alpha = texel.a;
      if (edge.x > 0.0) {
        float step = edge.x / max(edge.y, 1.0);
        alpha = max(alpha, artwork(uv + vec2(step, 0.0)).a);
        alpha = max(alpha, artwork(uv - vec2(step, 0.0)).a);
        alpha = max(alpha, artwork(uv + vec2(0.0, step)).a);
        alpha = max(alpha, artwork(uv - vec2(0.0, step)).a);
        alpha = max(alpha, artwork(uv + vec2(step, step) * 0.7071).a);
        alpha = max(alpha, artwork(uv - vec2(step, step) * 0.7071).a);
        alpha = max(alpha, artwork(uv + vec2(step, -step) * 0.7071).a);
        alpha = max(alpha, artwork(uv - vec2(step, -step) * 0.7071).a);
      }
      float stroke = (alpha - texel.a) * outline.a;
      float coverage = texel.a + stroke;
      if (coverage <= 0.0) discard;
      vec3 fill = icon.y > 0.5 ? texel.rgb : color;
      gl_FragColor = vec4((fill * texel.a + outline.rgb * stroke) / coverage, coverage * style.y);
    } else {
      float d;
      if (style.x < 0.5) d = (length(local) - 1.0) * edge.y * 0.5;
      else if (style.x < 1.5) d = (abs(local.x) + abs(local.y) - 1.0) * edge.y * 0.353553;
      else {
        float radius = edge.y * 0.25;
        vec2 q = abs(local * edge.y * 0.5) - vec2(edge.y * 0.5 - radius);
        d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - radius;
      }
      float coverage = 1.0 - smoothstep(-0.75, 0.75, d);
      if (coverage <= 0.0) discard;
      float stroke = edge.x > 0.0 ? smoothstep(-edge.x - 0.75, -edge.x + 0.75, d) : 0.0;
      gl_FragColor = vec4(mix(color, outline.rgb, stroke), coverage * style.y);
    }
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`

export const linkVertexShader = `
  attribute vec3 startHigh;
  attribute vec3 startLow;
  attribute vec3 endHigh;
  attribute vec3 endLow;
  attribute vec3 tint;
  attribute vec4 appearance;
  attribute float suggestion;
  attribute float curvature;
  attribute vec2 curveRange;
  uniform vec3 originHigh;
  uniform vec3 originLow;
  uniform vec2 viewport;
  uniform float cameraNear;
  uniform float detailed;
  varying vec3 color;
  varying vec3 style;
  varying vec2 local;
  void main() {
    vec3 a = mat3(viewMatrix) * ((startHigh - originHigh) + (startLow - originLow));
    vec3 b = mat3(viewMatrix) * ((endHigh - originHigh) + (endLow - originLow));
    float hidden = step(-cameraNear, a.z) * step(-cameraNear, b.z);
    // Clip before perspective division: crossing the camera cannot create an
    // enormous quad or hide a visible half of a relation.
    if (a.z > -cameraNear && b.z < -cameraNear) a = mix(a, b, (-cameraNear - a.z) / (b.z - a.z));
    if (b.z > -cameraNear && a.z <= -cameraNear) b = mix(b, a, (-cameraNear - b.z) / (a.z - b.z));
    vec4 ac = projectionMatrix * vec4(a, 1.0);
    vec4 bc = projectionMatrix * vec4(b, 1.0);
    vec2 delta = (bc.xy / max(bc.w, cameraNear) - ac.xy / max(ac.w, cameraNear)) * viewport * 0.5;
    float lengthPx = max(length(delta), 0.0001);
    vec2 normal = vec2(-delta.y, delta.x) / lengthPx;
    // Match the 2D quadratic control point in screen space. Bound its offset
    // when an endpoint crosses the camera plane or lies far outside the view.
    float limit = max(viewport.x, viewport.y) * 2.0;
    float bend = clamp(curvature * lengthPx, -limit, limit);
    float t = curveRange.x + position.x * curveRange.y;
    vec2 tangent = delta + normal * (2.0 * bend * (1.0 - 2.0 * t));
    vec2 side = vec2(-tangent.y, tangent.x) / max(length(tangent), 0.0001);
    float width = mix(appearance.x, appearance.y, detailed);
    vec2 screen = mix(ac.xy / max(ac.w, cameraNear), bc.xy / max(bc.w, cameraNear), t);
    vec2 offset = normal * (2.0 * bend * t * (1.0 - t)) + side * position.y * (width + 1.0);
    // Screen-space interpolation also keeps widths and dashes uniform between
    // endpoints at different depths; their depth still participates in clipping.
    vec4 clip = vec4(screen + offset * 2.0 / viewport,
      mix(ac.z / max(ac.w, cameraNear), bc.z / max(bc.w, cameraNear), t), 1.0);
    if (hidden > 0.5) clip = vec4(2.0, 2.0, 2.0, 1.0);
    gl_Position = clip;
    // Simpson's approximation keeps dash spacing continuous through joins and
    // through detail changes, without a CPU tessellation on camera movement.
    float arc = lengthPx * t;
    if (suggestion > 0.5) {
      float slope = 2.0 * bend / lengthPx;
      float startSpeed = length(vec2(1.0, slope));
      float midSpeed = length(vec2(1.0, slope * (1.0 - t)));
      float endSpeed = length(vec2(1.0, slope * (1.0 - 2.0 * t)));
      arc *= (startSpeed + 4.0 * midSpeed + endSpeed) / 6.0;
    }
    local = vec2(arc, position.y * (width + 1.0));
    color = tint;
    style = vec3(width, mix(appearance.z, appearance.w, detailed), suggestion);
  }
`

export const linkFragmentShader = `
  varying vec3 color;
  varying vec3 style;
  varying vec2 local;
  void main() {
    if (style.z > 0.5 && mod(local.x, max(3.0, style.x * 6.0)) > max(1.5, style.x * 3.0)) discard;
    float coverage = 1.0 - smoothstep(style.x * 0.5 - 0.5, style.x * 0.5 + 0.5, abs(local.y));
    if (coverage <= 0.0) discard;
    gl_FragColor = vec4(color, coverage * style.y);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`
