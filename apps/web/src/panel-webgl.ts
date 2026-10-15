import {
  PROFILE_INTERVALS,
  PROFILE_SAMPLE_COUNT,
  SELECTED_SLICE_ID,
  SLICE_COUNT,
  SOURCE_SIZE,
  type Slice,
} from './geometry';

const GL_OPTIONS: WebGLContextAttributes = {
  alpha: true,
  antialias: false,
  depth: false,
  stencil: false,
  premultipliedAlpha: true,
};
const GRIT_TILE_SIZE = 180;
const GRIT_TEXTURE_SIZE = GRIT_TILE_SIZE * 2;
const EDGE_WIDTH = 0.6;
const RIM_HALF_WIDTH = EDGE_WIDTH / 2;
const EDGE_PAD = 1.5;
const CLIP_BOTTOM = SOURCE_SIZE;
const OCCLUSION_MARGIN = 2;
const REVEAL_RIGHT = 10;
const RIM_ALPHA = 0.32;
const SIGNAL_RIM_ALPHA = 0.8;
const GRIT_ALPHA = 0.035;
const SIGNAL_GRIT_ALPHA = 0.02;
const FACE_HUE = '#fb8f52';
const FACE_BRIGHT = '#f26a2e';
const RIM_COLOR = '#fdfdfc';
const SOFT_RIM_COLOR = '#e2e1de';
const SIGNAL_RIM_COLOR = '#f18443';

const VERTEX_SHADER = `#version 300 es
precision highp float;
precision highp int;

const vec4 OFFSCREEN = vec4(2.0, 2.0, 2.0, 1.0);
uniform highp sampler2D u_profiles;
uniform highp sampler2D u_slices;
uniform highp sampler2D u_state;
uniform vec2 u_resolution;
uniform float u_step;
uniform float u_revealRight;
uniform float u_clipBottom;
uniform float u_occlusionMarginPx;
uniform int u_sliceBase;
uniform float u_rimHalfWidth;
uniform float u_edgePadPx;
uniform vec3 u_signalHue;
uniform vec3 u_signalBright;
uniform vec3 u_rim;
uniform vec3 u_rimSoft;
uniform vec3 u_signalRim;
uniform float u_rimAlpha;
uniform float u_signalRimAlpha;
uniform float u_gritAlpha;
uniform float u_signalGritAlpha;

out vec2 v_art;
out float v_depth;
out float v_slope;
flat out vec4 v_face;
flat out vec3 v_grit;
flat out vec4 v_rim;
flat out float v_reveal;

vec4 clipPosition(vec4 pose, vec2 art) {
  vec2 clip = (pose.xy + art * pose.z) / u_resolution * 2.0 - 1.0;
  return vec4(clip.x, -clip.y, 0.0, 1.0);
}

float coverTop(int slice, vec4 pose, float right, int column) {
  int cover = int(texelFetch(u_slices, ivec2(1, slice), 0).w);
  if (cover < 0) return -1.0;
  vec4 coverPose = texelFetch(u_state, ivec2(0, cover), 0);
  vec4 coverStyle = texelFetch(u_state, ivec2(1, cover), 0);
  if (coverPose != vec4(pose.xyz, 1.0) || coverStyle.x < 1.0 || right > coverStyle.z + u_revealRight) return -1.0;
  return texelFetch(u_profiles, ivec2(column, cover), 0).r + u_occlusionMarginPx / pose.z;
}

void main() {
  int slice = u_sliceBase + gl_InstanceID;
  vec4 pose = texelFetch(u_state, ivec2(0, slice), 0);
  if (pose.w < 0.5) {
    gl_Position = OFFSCREEN;
    return;
  }
  vec4 style = texelFetch(u_state, ivec2(1, slice), 0);
  int column = gl_VertexID / 3;
  int row = gl_VertexID - column * 3;
  vec2 profile = texelFetch(u_profiles, ivec2(column, slice), 0).rg;
  float x = float(column) * u_step;
  float y = profile.x;
  if (row == 0) y -= u_rimHalfWidth + u_edgePadPx / pose.z;
  if (row == 2) {
    float covered = coverTop(slice, pose, x + u_step, column);
    y = covered < 0.0 ? u_clipBottom : clamp(covered, profile.x, u_clipBottom);
  }
  vec4 face = texelFetch(u_slices, ivec2(0, slice), 0);
  vec4 info = texelFetch(u_slices, ivec2(1, slice), 0);
  bool isSignal = mod(info.z, 2.0) >= 1.0;
  bool soft = info.z >= 2.0;
  v_art = vec2(x, y);
  v_depth = y - profile.x;
  v_slope = profile.y;
  v_face = vec4(isSignal ? mix(u_signalHue, u_signalBright, style.y) : face.rgb, face.a * style.x);
  v_grit = vec3(info.xy, (isSignal ? u_signalGritAlpha : u_gritAlpha) * style.x * (1.0 - style.w));
  v_rim = vec4(isSignal ? u_signalRim : (soft ? u_rimSoft : u_rim), (isSignal ? u_signalRimAlpha : u_rimAlpha) * style.x);
  v_reveal = style.z;
  gl_Position = clipPosition(pose, v_art);
}`;

const FRAGMENT_SHADER = `#version 300 es
precision highp float;

in vec2 v_art;
in float v_depth;
in float v_slope;
flat in vec4 v_face;
flat in vec3 v_grit;
flat in vec4 v_rim;
flat in float v_reveal;
uniform sampler2D u_grit;
uniform float u_gritTile;
uniform float u_lineWidth;
uniform float u_revealRight;
uniform float u_clipBottom;
out vec4 outColor;

float lineCoverage(float distance, float width, float pixel) {
  float drawn = max(width, pixel);
  return clamp((0.5 * drawn - distance) / pixel + 0.5, 0.0, 1.0) * (width / drawn);
}

vec4 over(vec4 source, vec4 destination) {
  return source + destination * (1.0 - source.a);
}

void main() {
  float cosSlope = inversesqrt(1.0 + v_slope * v_slope);
  float depth = v_depth * cosSlope;
  float pixel = max(fwidth(depth), 1e-4);
  vec4 grit = texture(u_grit, (v_art + v_grit.xy) / u_gritTile);
  if (v_art.x > v_reveal + u_revealRight || v_art.y > u_clipBottom) discard;
  float fill = clamp(depth / pixel + 0.5, 0.0, 1.0);
  float faceAlpha = v_face.a * fill;
  vec4 color = over(grit * (v_grit.z * fill), vec4(v_face.rgb * faceAlpha, faceAlpha));
  float rimAlpha = v_rim.a * lineCoverage(abs(depth), u_lineWidth, pixel);
  color = over(vec4(v_rim.rgb * rimAlpha, rimAlpha), color);
  if (color.a < 0.002) discard;
  outColor = color;
}`;

export type PanelMaterial = {
  isSignal: boolean;
  brightness: number;
  revealEdge: number;
  plain: number;
};

export type PanelPose = {
  profile: Slice;
  x: number;
  y: number;
  scale: number;
  opacity: number;
  material: PanelMaterial;
};

export type PanelRenderer = {
  resize(cssWidth: number, cssHeight: number, dpr: number): void;
  draw(poses: readonly PanelPose[], clear?: boolean): void;
  isAvailable(): boolean;
  dispose(): void;
};

type Uniforms = {
  resolution: WebGLUniformLocation | null;
  step: WebGLUniformLocation | null;
  sliceBase: WebGLUniformLocation | null;
  revealRight: WebGLUniformLocation | null;
  clipBottom: WebGLUniformLocation | null;
};

function colorChannels(hex: string): readonly [number, number, number] {
  const value = Number.parseInt(hex.slice(1), 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

function normalizedColor(hex: string): Float32Array {
  return new Float32Array(colorChannels(hex).map((channel) => channel / 255));
}

function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    let value = state = (state + 0x6d2b79f5) >>> 0;
    value = Math.imul(value ^ value >>> 15, 1 | value);
    value ^= value + Math.imul(value ^ value >>> 7, 61 | value);
    return ((value ^ value >>> 14) >>> 0) / 0x100000000;
  };
}

function gritBytes(): Uint8Array {
  const bytes = new Uint8Array(GRIT_TEXTURE_SIZE * GRIT_TEXTURE_SIZE * 4);
  const random = seededRandom(101 * 21 + 11);
  const nearBlack = colorChannels('#21201c');
  const gray = colorChannels('#82827c');
  for (let pixel = 0; pixel < GRIT_TEXTURE_SIZE * GRIT_TEXTURE_SIZE; pixel += 1) {
    if (random() > 0.1) continue;
    const color = random() < 0.55 ? nearBlack : gray;
    const offset = pixel * 4;
    bytes[offset] = color[0];
    bytes[offset + 1] = color[1];
    bytes[offset + 2] = color[2];
    bytes[offset + 3] = Math.floor(40 + 120 * random());
  }

  const canvas = typeof document === 'undefined' ? null : document.createElement('canvas');
  if (canvas === null) return bytes;
  canvas.width = GRIT_TEXTURE_SIZE;
  canvas.height = GRIT_TEXTURE_SIZE;
  const context = canvas.getContext('2d');
  if (context === null) return bytes;
  const image = context.createImageData(GRIT_TEXTURE_SIZE, GRIT_TEXTURE_SIZE);
  image.data.set(bytes);
  context.putImageData(image, 0, 0);
  const fill = (color: readonly number[], alpha: number, x: number, y: number, rx: number, ry: number, rotation: number) => {
    context.globalAlpha = alpha;
    context.fillStyle = `rgb(${color[0]}, ${color[1]}, ${color[2]})`;
    context.beginPath();
    context.ellipse(x, y, rx, ry, rotation, 0, 2 * Math.PI);
    context.fill();
  };
  for (let ellipse = 0; ellipse < 30; ellipse += 1) {
    const color = random() < 0.6 ? nearBlack : gray;
    fill(color, 0.25 + 0.4 * random(), random() * GRIT_TEXTURE_SIZE, random() * GRIT_TEXTURE_SIZE,
      (0.5 + random()) * 2, (0.4 + 0.8 * random()) * 2, random() * Math.PI);
  }
  context.globalAlpha = 1;
  return new Uint8Array(context.getImageData(0, 0, GRIT_TEXTURE_SIZE, GRIT_TEXTURE_SIZE).data);
}

function compileShader(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader {
  const shader = gl.createShader(type);
  if (shader === null) throw new Error('Could not create panel shader');
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const message = gl.getShaderInfoLog(shader) ?? 'No shader log';
    gl.deleteShader(shader);
    throw new Error(`Panel shader failed to compile: ${message}`);
  }
  return shader;
}

function createProgram(gl: WebGL2RenderingContext): WebGLProgram {
  const vertex = compileShader(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
  const fragment = compileShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
  const program = gl.createProgram();
  if (program === null) throw new Error('Could not create panel program');
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  gl.deleteShader(vertex);
  gl.deleteShader(fragment);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    const message = gl.getProgramInfoLog(program) ?? 'No program log';
    gl.deleteProgram(program);
    throw new Error(`Panel program failed to link: ${message}`);
  }
  return program;
}

function createFloatTexture(
  gl: WebGL2RenderingContext,
  unit: number,
  internalFormat: number,
  format: number,
  width: number,
  height: number,
  data: Float32Array | null,
): WebGLTexture {
  const texture = gl.createTexture();
  if (texture === null) throw new Error('Could not create panel data texture');
  gl.activeTexture(gl.TEXTURE0 + unit);
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texImage2D(gl.TEXTURE_2D, 0, internalFormat, width, height, 0, format, gl.FLOAT, data);
  return texture;
}

function createIndexBuffer(gl: WebGL2RenderingContext): { vao: WebGLVertexArrayObject; buffer: WebGLBuffer; count: number } {
  const vao = gl.createVertexArray();
  const buffer = gl.createBuffer();
  if (vao === null || buffer === null) throw new Error('Could not create panel draw buffers');
  const indices: number[] = [];
  for (let column = 0; column < PROFILE_INTERVALS; column += 1) {
    for (let row = 0; row < 2; row += 1) {
      const first = 3 * column + row;
      const next = 3 * (column + 1) + row;
      indices.push(first, first + 1, next, next, first + 1, next + 1);
    }
  }
  gl.bindVertexArray(vao);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(indices), gl.STATIC_DRAW);
  gl.bindVertexArray(null);
  return { vao, buffer, count: indices.length };
}

function uploadStaticTextures(gl: WebGL2RenderingContext, program: WebGLProgram, profiles: readonly Slice[]) {
  const profileData = new Float32Array(PROFILE_SAMPLE_COUNT * profiles.length * 2);
  const sliceData = new Float32Array(profiles.length * 8);
  const coverIndices = profiles.map((_, index) => profiles.findIndex((later, laterIndex) => laterIndex > index && later.alpha >= 1));

  profiles.forEach((profile, sliceIndex) => {
    profile.points.forEach((point, sampleIndex) => {
      const previous = profile.points[Math.max(0, sampleIndex - 1)];
      const next = profile.points[Math.min(PROFILE_INTERVALS, sampleIndex + 1)];
      const sampleStep = (Math.min(PROFILE_INTERVALS, sampleIndex + 1) - Math.max(0, sampleIndex - 1))
        * (SOURCE_SIZE / PROFILE_INTERVALS);
      const offset = (sliceIndex * PROFILE_SAMPLE_COUNT + sampleIndex) * 2;
      profileData[offset] = point.y;
      profileData[offset + 1] = (next.y - previous.y) / sampleStep;
    });

    const [red, green, blue] = normalizedColor(profile.color);
    const offset = sliceIndex * 8;
    sliceData.set([red, green, blue, profile.alpha, profile.gritOffset.x, profile.gritOffset.y,
      Number(profile.id === SELECTED_SLICE_ID) + 2 * Number(profile.soft), coverIndices[sliceIndex] ?? -1], offset);
  });

  const profileTexture = createFloatTexture(gl, 1, gl.RG32F, gl.RG, PROFILE_SAMPLE_COUNT, profiles.length, profileData);
  const sliceTexture = createFloatTexture(gl, 2, gl.RGBA32F, gl.RGBA, 2, profiles.length, sliceData);
  const stateTexture = createFloatTexture(gl, 3, gl.RGBA32F, gl.RGBA, 2, profiles.length, null);

  gl.useProgram(program);
  const samplers = [['u_grit', 0], ['u_profiles', 1], ['u_slices', 2], ['u_state', 3]] as const;
  for (const [name, unit] of samplers) gl.uniform1i(gl.getUniformLocation(program, name), unit);
  gl.uniform1f(gl.getUniformLocation(program, 'u_step'), SOURCE_SIZE / PROFILE_INTERVALS);
  gl.uniform1f(gl.getUniformLocation(program, 'u_revealRight'), REVEAL_RIGHT);
  gl.uniform1f(gl.getUniformLocation(program, 'u_clipBottom'), CLIP_BOTTOM);
  gl.uniform1f(gl.getUniformLocation(program, 'u_occlusionMarginPx'), OCCLUSION_MARGIN);
  gl.uniform1f(gl.getUniformLocation(program, 'u_rimHalfWidth'), RIM_HALF_WIDTH);
  gl.uniform1f(gl.getUniformLocation(program, 'u_edgePadPx'), EDGE_PAD);
  gl.uniform3fv(gl.getUniformLocation(program, 'u_signalHue'), normalizedColor(FACE_HUE));
  gl.uniform3fv(gl.getUniformLocation(program, 'u_signalBright'), normalizedColor(FACE_BRIGHT));
  gl.uniform3fv(gl.getUniformLocation(program, 'u_rim'), normalizedColor(RIM_COLOR));
  gl.uniform3fv(gl.getUniformLocation(program, 'u_rimSoft'), normalizedColor(SOFT_RIM_COLOR));
  gl.uniform3fv(gl.getUniformLocation(program, 'u_signalRim'), normalizedColor(SIGNAL_RIM_COLOR));
  gl.uniform1f(gl.getUniformLocation(program, 'u_rimAlpha'), RIM_ALPHA);
  gl.uniform1f(gl.getUniformLocation(program, 'u_signalRimAlpha'), SIGNAL_RIM_ALPHA);
  gl.uniform1f(gl.getUniformLocation(program, 'u_gritAlpha'), GRIT_ALPHA);
  gl.uniform1f(gl.getUniformLocation(program, 'u_signalGritAlpha'), SIGNAL_GRIT_ALPHA);
  gl.uniform1f(gl.getUniformLocation(program, 'u_gritTile'), GRIT_TILE_SIZE);
  gl.uniform1f(gl.getUniformLocation(program, 'u_lineWidth'), EDGE_WIDTH);

  return { profileTexture, sliceTexture, stateTexture };
}

function createGritTexture(gl: WebGL2RenderingContext): WebGLTexture {
  const texture = gl.createTexture();
  if (texture === null) throw new Error('Could not create panel grit texture');
  gl.activeTexture(gl.TEXTURE0);
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, 1);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, GRIT_TEXTURE_SIZE, GRIT_TEXTURE_SIZE, 0, gl.RGBA, gl.UNSIGNED_BYTE, gritBytes());
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, 0);
  gl.generateMipmap(gl.TEXTURE_2D);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.REPEAT);
  return texture;
}

function setState(poses: readonly PanelPose[], dpr: number): Float32Array {
  const state = new Float32Array(poses.length * 8);
  poses.forEach((pose, index) => {
    const offset = index * 8;
    const visible = pose.opacity > 0 && pose.scale > 0;
    state.set([pose.x * dpr, pose.y * dpr, pose.scale * dpr, Number(visible),
      pose.opacity, pose.material.brightness, pose.material.revealEdge, pose.material.plain], offset);
  });
  return state;
}

function drawRuns(gl: WebGL2RenderingContext, uniforms: Uniforms, indexCount: number, poses: readonly PanelPose[]): void {
  const runs: Array<[number, number]> = [];
  for (let index = 0; index < poses.length; index += 1) {
    const pose = poses[index];
    if (pose === undefined || pose.opacity <= 0 || pose.scale <= 0) continue;
    const previous = runs[runs.length - 1];
    if (previous !== undefined && previous[1] === index - 1) previous[1] = index;
    else runs.push([index, index]);
  }
  for (const [start, end] of runs) {
    gl.uniform1i(uniforms.sliceBase, start);
    gl.drawElementsInstanced(gl.TRIANGLES, indexCount, gl.UNSIGNED_SHORT, 0, end - start + 1);
  }
}

type PanelResources = {
  program: WebGLProgram;
  gritTexture: WebGLTexture;
  buffers: ReturnType<typeof createIndexBuffer>;
  uniforms: Uniforms;
  staticData: ReturnType<typeof uploadStaticTextures> | null;
};

function createResources(gl: WebGL2RenderingContext): PanelResources {
  const program = createProgram(gl);
  const gritTexture = createGritTexture(gl);
  const buffers = createIndexBuffer(gl);
  const uniforms: Uniforms = {
    resolution: gl.getUniformLocation(program, 'u_resolution'),
    step: gl.getUniformLocation(program, 'u_step'),
    sliceBase: gl.getUniformLocation(program, 'u_sliceBase'),
    revealRight: gl.getUniformLocation(program, 'u_revealRight'),
    clipBottom: gl.getUniformLocation(program, 'u_clipBottom'),
  };
  return { program, gritTexture, buffers, uniforms, staticData: null };
}

function deleteResources(gl: WebGL2RenderingContext, resources: PanelResources): void {
  if (resources.staticData !== null) {
    gl.deleteTexture(resources.staticData.profileTexture);
    gl.deleteTexture(resources.staticData.sliceTexture);
    gl.deleteTexture(resources.staticData.stateTexture);
  }
  gl.deleteTexture(resources.gritTexture);
  gl.deleteBuffer(resources.buffers.buffer);
  gl.deleteVertexArray(resources.buffers.vao);
  gl.deleteProgram(resources.program);
}

export function createPanelRenderer(canvas: HTMLCanvasElement): PanelRenderer | null {
  let gl: WebGL2RenderingContext | null = null;
  let resources: PanelResources | null = null;
  try {
    gl = canvas.getContext('webgl2', GL_OPTIONS);
    if (gl === null) return null;
    resources = createResources(gl);
    let dpr = 1;
    let available = true;
    let disposed = false;
    let previousPoses: readonly PanelPose[] | null = null;

    const drawFrame = (poses: readonly PanelPose[], clear: boolean): void => {
      if (disposed || gl === null || resources === null || !available || poses.length !== SLICE_COUNT) return;
      try {
        if (resources.staticData === null) {
          resources.staticData = uploadStaticTextures(gl, resources.program, poses.map((pose) => pose.profile));
        }
        gl.viewport(0, 0, canvas.width, canvas.height);
        if (clear) {
          gl.clearColor(0, 0, 0, 0);
          gl.clear(gl.COLOR_BUFFER_BIT);
        }
        gl.activeTexture(gl.TEXTURE0 + 3);
        gl.bindTexture(gl.TEXTURE_2D, resources.staticData.stateTexture);
        gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, 2, poses.length, gl.RGBA, gl.FLOAT, setState(poses, dpr));
        gl.useProgram(resources.program);
        gl.uniform2f(resources.uniforms.resolution, canvas.width, canvas.height);
        gl.bindVertexArray(resources.buffers.vao);
        gl.enable(gl.BLEND);
        gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
        drawRuns(gl, resources.uniforms, resources.buffers.count, poses);
        gl.bindVertexArray(null);
      } catch {
        available = false;
      }
    };

    const onLost = (event: Event) => {
      event.preventDefault();
      available = false;
    };
    const onRestored = () => {
      if (gl === null || disposed) return;
      try {
        resources = createResources(gl);
        available = true;
        if (previousPoses !== null) drawFrame(previousPoses, true);
      } catch {
        available = false;
      }
    };
    canvas.addEventListener('webglcontextlost', onLost);
    canvas.addEventListener('webglcontextrestored', onRestored);

    return {
      resize(cssWidth, cssHeight, nextDpr) {
        if (disposed || gl === null) return;
        dpr = Number.isFinite(nextDpr) && nextDpr > 0 ? nextDpr : 1;
        canvas.width = Math.max(1, Math.round(cssWidth * dpr));
        canvas.height = Math.max(1, Math.round(cssHeight * dpr));
        gl.viewport(0, 0, canvas.width, canvas.height);
      },
      draw(poses, clear = true) {
        previousPoses = poses;
        drawFrame(poses, clear);
      },
      isAvailable() {
        return available && !disposed;
      },
      dispose() {
        if (disposed) return;
        disposed = true;
        canvas.removeEventListener('webglcontextlost', onLost);
        canvas.removeEventListener('webglcontextrestored', onRestored);
        if (gl !== null && resources !== null) deleteResources(gl, resources);
        resources = null;
      },
    };
  } catch {
    if (gl !== null) {
      if (resources !== null) deleteResources(gl, resources);
      gl.getExtension('WEBGL_lose_context')?.loseContext();
    }
    return null;
  }
}
