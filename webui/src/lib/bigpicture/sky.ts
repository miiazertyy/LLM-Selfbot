/**
 * Big Picture's moving background, drawn by the graphics card.
 *
 * The app's own background, made personal: four big, soft blooms of light
 * drifting past each other, squashing and stretching a little as they go
 * like the app's jelly, in the colours of whoever is on stage (palette.ts) and
 * moving their way (looks.ts). Nothing in it has an edge or a texture: it is a
 * background, felt more than watched. A new palette or look is never cut to:
 * every dial eases towards its new setting, so one room melts into the next
 * over a second or two. A reply going out makes the blooms swell and settle
 * on a spring.
 *
 * It stays a dark room: the result is tone-mapped and capped, because every
 * panel over it is glass and every accent on them glows, and neither reads on
 * a bright ground. It is drawn at half the screen's resolution, sixty frames a
 * second, and dithered with a fixed pattern, since a smooth dark gradient
 * bands in eight bits. It used to be a third of the resolution at thirty
 * frames with a dither that changed every frame: stretched three times over
 * by the browser, the lights moved in visible steps (the one that follows
 * the pointer most of all) and the grain shimmered. With the motion setting
 * off it draws one still frame, and again only when the colours change.
 */
import { LOOKS, dials, type Look } from "./looks";
import type { RGB } from "./palette";

const VERT = "attribute vec2 a_pos; void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }";

const FRAG = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
uniform vec2 u_res;
uniform float u_time;
uniform vec3 u_c0;
uniform vec3 u_c1;
uniform vec3 u_c2;
uniform vec3 u_c3;
uniform vec4 u_look;   // wobble, size, speed, orbit
uniform float u_glow;
uniform float u_energy;
uniform float u_age;   // seconds since a reply last went out
uniform vec2 u_focus;  // where the stage is, 0..1
uniform vec2 u_mouse;  // the pointer, 0..1, eased

float hash21(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}
vec2 turn(vec2 v, float a) {
  float c = cos(a);
  float s = sin(a);
  return vec2(c * v.x - s * v.y, s * v.x + c * v.y);
}
// One bloom of light: bright in the middle and fading to nothing, with no edge
// anywhere. It squashes one way and stretches the other as it goes, on an axis
// that turns slowly: the jelly.
float bloom(vec2 p, vec2 c, float r, float wob, float t, float seed) {
  vec2 d = turn(p - c, t * 0.35 + seed * 6.2831);
  float sq = wob * sin(t * 1.1 + seed * 9.0);
  d *= vec2(1.0 + sq, 1.0 - sq);
  return exp(-dot(d, d) / (r * r) * 1.7);
}
void main() {
  vec2 uv = gl_FragCoord.xy / u_res;
  float asp = u_res.x / u_res.y;
  // The room leans a little away from the pointer.
  vec2 p = (uv - 0.5) * vec2(asp, 1.0) + (u_mouse - 0.5) * vec2(0.05, 0.035);
  vec2 f = (u_focus - 0.5) * vec2(asp, 1.0);
  float t = u_time * (0.05 + 0.12 * u_look.z) * (1.0 + 0.6 * u_energy);
  float wob = 0.04 + 0.12 * u_look.x;
  // A reply gone: every bloom swells and settles on a spring, the way the app's jelly does.
  float bounce = exp(-u_age * 2.4) * sin(u_age * 10.0) * 0.2;
  float r = mix(0.42, 0.78, u_look.y) * (1.0 + bounce);
  // Turning round the stage, as much as the look turns.
  float spin = u_look.w * t * 0.35;

  // Four blooms, one to a colour, drifting on slow loops past each other.
  vec2 a = f + turn(vec2(-0.62, 0.24) + 0.26 * vec2(sin(t * 0.9), cos(t * 0.7)), spin);
  vec2 b = f + turn(vec2(0.58, -0.22) + 0.24 * vec2(cos(t * 0.8 + 1.0), sin(t * 0.6 + 2.0)), spin);
  vec2 c = f + 0.16 * vec2(sin(t * 0.5 + 3.0), cos(t * 0.8 + 1.0));
  vec2 e = f + turn(vec2(0.15, 0.4) + 0.28 * vec2(sin(t * 0.4 + 4.0), cos(t * 0.5)), spin);
  vec3 light = u_c0 * bloom(p, a, r * 1.1, wob, t, 0.1)
             + u_c1 * bloom(p, b, r, wob, t, 0.4)
             // the one behind the stage warms while a reply is written and typed
             + u_c2 * bloom(p, c, r * 0.8, wob, t, 0.7) * (0.6 + 0.5 * u_energy)
             + u_c3 * bloom(p, e, r * 0.9, wob, t, 0.9) * 0.75;
  vec3 col = light * 0.4 * u_glow;
  // and a soft brightening behind the stage as a reply goes
  vec2 fd = p - f;
  col += u_c2 * exp(-u_age * 2.2) * exp(-dot(fd, fd) * 3.0) * 0.22;

  // A dark room, always: it sits behind glass and white text.
  col = 1.0 - exp(-col * 1.2);
  col = min(col, vec3(0.45));
  float vig = smoothstep(1.2, 0.25, length((uv - vec2(0.5, 0.52)) * vec2(1.1, 1.25)));
  col *= mix(0.55, 1.0, vig);
  col += vec3(0.012, 0.014, 0.03);
  // Dither: a smooth dark gradient bands in eight bits without it. A fixed
  // pattern: one that changes every frame shimmers once it is stretched.
  col += (hash21(gl_FragCoord.xy) - 0.5) * (1.5 / 255.0);
  gl_FragColor = vec4(col, 1.0);
}
`;

const UNIFORMS = ["u_res", "u_time", "u_c0", "u_c1", "u_c2", "u_c3", "u_look", "u_glow", "u_energy", "u_age",
  "u_focus", "u_mouse"] as const;

export type SkyTarget = {
  palette: RGB[];
  look: Look;
  /** 0 calm, 1 lively. */
  energy: number;
  /** Where across the screen the stage is, 0 to 1. */
  focus?: number;
};

/**
 * A shader handed to the driver to compile. Not asked whether it compiled:
 * asking waits for it, and the program's link status says so anyway.
 */
function start(gl: WebGLRenderingContext, type: number, src: string): WebGLShader | null {
  const s = gl.createShader(type);
  if (!s) return null;
  gl.shaderSource(s, src);
  gl.compileShader(s);
  return s;
}

/** Four colours, whatever was given: repeated round if fewer. */
const four = (p: RGB[]): number[][] => [0, 1, 2, 3].map((i) => [...(p[i % Math.max(1, p.length)] ?? [0.4, 0.4, 0.8])]);

export class Sky {
  /** Called if the graphics card takes the canvas back; the caller draws the room another way. */
  onLost: (() => void) | null = null;
  private loc = {} as Record<(typeof UNIFORMS)[number], WebGLUniformLocation | null>;
  private pal: number[][] = four([]);
  private palT: number[][] = four([]);
  private look = dials(LOOKS.silk);
  private lookT = dials(LOOKS.silk);
  private energy = 0.2;
  private energyT = 0.2;
  private focus = 0.45;
  private focusT = 0.45;
  private mouse = [0.5, 0.5];
  private mouseT = [0.5, 0.5];
  /** Seconds of movement so far, started somewhere different each time; frozen while still. */
  private clock = 40 + Math.random() * 400;
  private pulseAt = -1e4;
  private last = 0;
  private raf = 0;
  private still = false;
  private dead = false;
  /** The size it is shown at, in CSS pixels: told, since a worker's canvas cannot measure itself. */
  private cssW = 0;
  private cssH = 0;

  private constructor(
    private canvas: HTMLCanvasElement | OffscreenCanvas,
    private gl: WebGLRenderingContext,
    private prog: WebGLProgram,
    private buf: WebGLBuffer,
    private scale: number,
  ) {
    for (const u of UNIFORMS) this.loc[u] = gl.getUniformLocation(prog, u);
    canvas.addEventListener("webglcontextlost", this.lost);
  }

  /** A sky on this canvas, or null where WebGL is not available or the shader will not build. */
  /**
   * Made without holding up the page. The shader is handed to the graphics
   * driver to compile on a thread of its own where the browser allows it
   * (KHR_parallel_shader_compile, which Chrome and Edge have), and waited for
   * a frame at a time. Compiled in one go, as it was, it took a single frame
   * of 150 ms on an integrated GPU, in the middle of Big Picture's entrance.
   */
  static async create(canvas: HTMLCanvasElement | OffscreenCanvas, scale = 1 / 2): Promise<Sky | null> {
    let gl: WebGLRenderingContext | null = null;
    try {
      gl = canvas.getContext("webgl", {
        alpha: false, antialias: false, depth: false, stencil: false,
        premultipliedAlpha: false, preserveDrawingBuffer: false, powerPreference: "low-power",
      }) as WebGLRenderingContext | null;
    } catch {
      gl = null;
    }
    if (!gl) return null;
    const parallel = gl.getExtension("KHR_parallel_shader_compile") as { COMPLETION_STATUS_KHR: number } | null;
    const vs = start(gl, gl.VERTEX_SHADER, VERT);
    const fs = start(gl, gl.FRAGMENT_SHADER, FRAG);
    const prog = vs && fs ? gl.createProgram() : null;
    if (!prog || !vs || !fs) return null;
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (parallel) {
      // Asking for the result before it is ready would wait for it right here.
      while (!gl.getProgramParameter(prog, parallel.COMPLETION_STATUS_KHR)) {
        await new Promise((r) => requestAnimationFrame(r));
        if (gl.isContextLost()) return null;
      }
    }
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      console.warn("Big Picture background:", gl.getShaderInfoLog(vs), gl.getShaderInfoLog(fs), gl.getProgramInfoLog(prog));
      return null;
    }
    // One triangle bigger than the screen: every pixel is drawn exactly once.
    const buf = gl.createBuffer();
    if (!buf) return null;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const at = gl.getAttribLocation(prog, "a_pos");
    gl.enableVertexAttribArray(at);
    gl.vertexAttribPointer(at, 2, gl.FLOAT, false, 0, 0);
    gl.useProgram(prog);
    return new Sky(canvas, gl, prog, buf, scale);
  }

  /** Where it is headed; `now` jumps straight there instead of easing. */
  set(t: SkyTarget, now = false): void {
    this.palT = four(t.palette);
    this.lookT = dials(t.look);
    this.energyT = Math.min(1, Math.max(0, t.energy));
    this.focusT = t.focus ?? this.focusT;
    if (now) this.snap();
    if (this.still) this.kick();
  }

  /** A reply went out: a ring of light from the stage. */
  pulse(): void {
    if (!this.still) this.pulseAt = this.clock;
  }

  /** The size it is shown at, in CSS pixels; it draws at a third of that. */
  resize(w: number, h: number): void {
    this.cssW = w;
    this.cssH = h;
    if (this.still) this.kick();
  }

  /** The pointer, as a share of the screen across and down. */
  pointer(x: number, y: number): void {
    this.mouseT = [Math.min(1, Math.max(0, x)), 1 - Math.min(1, Math.max(0, y))];
  }

  /** Motion off: one still frame, drawn again only when something changes. */
  setStill(still: boolean): void {
    if (this.still === still) return;
    this.still = still;
    if (still) this.snap();
    this.kick();
  }

  start(): void {
    this.kick();
  }

  destroy(): void {
    this.dead = true;
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.canvas.removeEventListener("webglcontextlost", this.lost);
    const gl = this.gl;
    gl.deleteBuffer(this.buf);
    gl.deleteProgram(this.prog);
    gl.getExtension("WEBGL_lose_context")?.loseContext();
  }

  private lost = (e: Event) => {
    e.preventDefault();
    this.dead = true;
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.onLost?.();
  };

  private kick(): void {
    if (this.dead || this.raf) return;
    this.last = performance.now();
    this.raf = requestAnimationFrame(this.frame);
  }

  private snap(): void {
    this.pal = this.palT.map((c) => [...c]);
    this.look = [...this.lookT];
    this.energy = this.energyT;
    this.focus = this.focusT;
    this.mouse = [...this.mouseT];
  }

  private frame = (now: number) => {
    this.raf = 0;
    if (this.dead) return;
    if (this.still) {
      this.draw();
      return;                                   // nothing moves: no next frame until something changes
    }
    const dt = (now - this.last) / 1000;
    // About sixty frames a second: every frame on most screens, every other
    // one on a fast one. Thirty showed as steps in anything that moved.
    if (dt < 1 / 66) {
      this.raf = requestAnimationFrame(this.frame);
      return;
    }
    this.last = now;
    const step = Math.min(0.1, dt);             // back from a hidden tab: no leap
    this.clock += step;
    this.ease(step);
    this.draw();
    this.raf = requestAnimationFrame(this.frame);
  };

  /** Every dial part of the way to where it is headed: about two seconds to settle. */
  private ease(dt: number): void {
    const k = 1 - Math.exp(-dt * 1.7);
    const ke = 1 - Math.exp(-dt * 2.6);
    const km = 1 - Math.exp(-dt * 3);
    for (let i = 0; i < 4; i++) for (let j = 0; j < 3; j++) this.pal[i][j] += (this.palT[i][j] - this.pal[i][j]) * k;
    for (let i = 0; i < this.look.length; i++) this.look[i] += (this.lookT[i] - this.look[i]) * k;
    this.energy += (this.energyT - this.energy) * ke;
    this.focus += (this.focusT - this.focus) * k;
    this.mouse[0] += (this.mouseT[0] - this.mouse[0]) * km;
    this.mouse[1] += (this.mouseT[1] - this.mouse[1]) * km;
  }

  private draw(): void {
    const gl = this.gl;
    const c = this.canvas;
    // Told its size rather than reading it: reading a canvas's size in the page
    // every frame made the browser work out the whole layout early to answer.
    const w = Math.max(2, Math.round(this.cssW * this.scale));
    const h = Math.max(2, Math.round(this.cssH * this.scale));
    if (c.width !== w || c.height !== h) {
      c.width = w;
      c.height = h;
    }
    const L = this.loc;
    const [wobble, size, speed, orbit, glow] = this.look;
    gl.viewport(0, 0, w, h);
    gl.uniform2f(L.u_res, w, h);
    gl.uniform1f(L.u_time, this.clock);
    gl.uniform3fv(L.u_c0, this.pal[0]);
    gl.uniform3fv(L.u_c1, this.pal[1]);
    gl.uniform3fv(L.u_c2, this.pal[2]);
    gl.uniform3fv(L.u_c3, this.pal[3]);
    gl.uniform4f(L.u_look, wobble, size, speed, orbit);
    gl.uniform1f(L.u_glow, glow);
    gl.uniform1f(L.u_energy, this.energy);
    gl.uniform1f(L.u_age, this.still ? 1e3 : this.clock - this.pulseAt);
    gl.uniform2f(L.u_focus, this.focus, 0.58);
    gl.uniform2f(L.u_mouse, this.mouse[0], this.mouse[1]);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }
}
