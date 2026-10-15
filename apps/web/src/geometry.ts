export const ART_WIDTH = 1183;
export const ART_HEIGHT = 860;
export const SOURCE_SIZE = 1200;
export const SOURCE_BASELINE = 1240;
export const SLICE_COUNT = 220;
export const PROFILE_INTERVALS = 720;
export const PROFILE_SAMPLE_COUNT = PROFILE_INTERVALS + 1;
export const SELECTED_SLICE_ID = 122;
export const GRID_COLUMNS = 20;
export const GRID_ROWS = 11;
export const GRID_GAP_X = 0.14;
export const GRID_GAP_Y = 1.1;
export const CHART_TOP = 0;
export const CHART_BASE = SOURCE_BASELINE;
export const FAMILY_COLORS = ['#46a758', '#e5484d', '#ffc53d', '#2e7db5', '#f26a2e', '#63635e'] as const;
export const FAMILY_RIM_COLORS = ['#2a7e3b', '#ce2c31', '#ab6400', '#225d86', '#a94613', '#21201c'] as const;
export const FAMILY_NAMES = ['Forecasting', 'Risk management', 'Portfolio management', 'Systematic trading', 'Backtesting & simulation', 'Execution'] as const;

export type Point = { x: number; y: number };
export type Slice = {
  id: number;
  depth: number;
  points: Point[];
  baseline: number;
  color: string;
  alpha: number;
  isSelected: boolean;
  gritOffset: Point;
  soft: boolean;
  revealDelay: number;
  revealSweep: number;
};
export type GridCell = { id: number; column: number; row: number; x: number; y: number };

const OUTLINE = [
  [-0.486, 0], [-0.443, 0.12], [-0.389, 0.25], [-0.324, 0.33], [-0.275, 0.42],
  [-0.245, 0.48], [-0.21, 0.55], [-0.192, 0.66], [-0.174, 0.71], [-0.15, 0.67],
  [-0.109, 0.79], [-0.079, 0.86], [-0.049, 0.9], [-0.031, 0.87], [0.004, 0.93],
  [0.031, 0.97], [0.065, 1], [0.094, 0.93], [0.124, 0.84], [0.141, 0.85],
  [0.177, 0.75], [0.219, 0.7], [0.255, 0.72], [0.279, 0.65], [0.315, 0.54],
  [0.351, 0.46], [0.389, 0.37], [0.432, 0.2], [0.486, 0],
] as const satisfies readonly (readonly [number, number])[];

const COVERAGE_FEATURE = { slice: SELECTED_SLICE_ID, x: 0.15, width: 0.15, depth: 0.05 };
const RANDOM_BANDS = ['#10a37f', '#1a73e8', '#000000', '#f472b6', '#8e66ef', '#f77fb0'] as const;
const SELECTED_COLOR = '#fb8f52';
const MOUNTAIN_INK = '#383834';
const PAGE = '#f9f9f8';

function createSeededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    let value = state = (state + 0x6d2b79f5) >>> 0;
    value = Math.imul(value ^ value >>> 15, 1 | value);
    value ^= value + Math.imul(value ^ value >>> 7, 61 | value);
    return ((value ^ value >>> 14) >>> 0) / 0x100000000;
  };
}

function createNoise(seed: number): (x: number, y: number) => number {
  const latticeValue = (x: number, y: number) => {
    const random = createSeededRandom(0x466f45d * seed ^ 0x127409f * x ^ 0x4f9ffb7 * y);
    return random() * 2 - 1;
  };
  const smooth = (value: number) => value * value * (3 - 2 * value);

  return (x, y) => {
    const floorX = Math.floor(x);
    const floorY = Math.floor(y);
    const blendX = smooth(x - floorX);
    const blendY = smooth(y - floorY);
    const topLeft = latticeValue(floorX, floorY);
    const topRight = latticeValue(floorX + 1, floorY);
    const bottomLeft = latticeValue(floorX, floorY + 1);
    const bottomRight = latticeValue(floorX + 1, floorY + 1);
    return (topLeft + (topRight - topLeft) * blendX) * (1 - blendY)
      + (bottomLeft + (bottomRight - bottomLeft) * blendX) * blendY;
  };
}

function outlineHeight(x: number): number {
  if (x <= OUTLINE[0][0] || x >= OUTLINE[OUTLINE.length - 1][0]) return 0;
  let next = 1;
  while (OUTLINE[next]![0] < x) next += 1;
  const [leftX, leftY] = OUTLINE[next - 1]!;
  const [rightX, rightY] = OUTLINE[next]!;
  return leftY + (rightY - leftY) * (x - leftX) / (rightX - leftX);
}

function clampSmoothstep(start: number, end: number, value: number): number {
  const ratio = Math.max(0, Math.min(1, (value - start) / (end - start)));
  return ratio * ratio * (3 - 2 * ratio);
}

function featureMask(feature: typeof COVERAGE_FEATURE, x: number): number {
  const ratio = (x - (SOURCE_SIZE / 2 + feature.x * SOURCE_SIZE)) / (feature.width * SOURCE_SIZE / 2);
  return Math.abs(ratio) < 1 ? Math.pow(1 - ratio * ratio, 1.3) : 0;
}

function interpolateColor(color: string, background: string, mix: number, brightness: number): string {
  const source = Number.parseInt(color.slice(1), 16);
  const target = Number.parseInt(background.slice(1), 16);
  const channels = [16, 8, 0].map((shift) => {
    const left = (source >> shift) & 255;
    const right = (target >> shift) & 255;
    return Math.max(0, Math.min(255, Math.round((left + (right - left) * mix) * brightness)));
  });
  return `#${channels.map((channel) => channel.toString(16).padStart(2, '0')).join('')}`;
}

function makeFace(id: number, random: () => number): { color: string; alpha: number } {
  const isSelected = id === SELECTED_SLICE_ID;
  const isColored = isSelected || random() < 0.2;
  const colorIndex = Math.floor(random() * RANDOM_BANDS.length);
  const brightness = 1 + (2 * random() - 1) * 0.045;
  if (isSelected) return { color: interpolateColor(SELECTED_COLOR, PAGE, 0, brightness), alpha: 1 };
  if (isColored) return { color: interpolateColor(RANDOM_BANDS[colorIndex]!, PAGE, 0.12, brightness), alpha: 0.7 };
  return { color: interpolateColor(MOUNTAIN_INK, PAGE, 0, brightness), alpha: 1 };
}

function makeSlice(id: number, faceRandom: () => number, gritRandom: () => number, revealRandom: () => number): Slice {
  const depth = id / (SLICE_COUNT - 1);
  const ridge = createNoise(101 * 21 + 1);
  const detail = createNoise(101 * 21 + 2);
  const grain = createNoise(101 * 21 + 3);
  const drift = createNoise(101 * 21 + 4);
  const notch = createNoise(101 * 21 + 5);
  const crease = createNoise(101 * 21 + 6);
  const depthEnvelope = (slice: number) => 0.05 + (0.9 - 0.05) * Math.pow(slice / (SLICE_COUNT - 1), 0.55);
  const baseDepth = depthEnvelope(id);
  const adjustedDepth = id < COVERAGE_FEATURE.slice
    ? baseDepth + (depthEnvelope(COVERAGE_FEATURE.slice) * 1.03 - depthEnvelope(COVERAGE_FEATURE.slice - 1))
      * Math.pow((id + 1) / COVERAGE_FEATURE.slice, 0.35)
    : baseDepth;
  const face = makeFace(id, faceRandom);
  const gritOffset = { x: gritRandom() * 180, y: gritRandom() * 180 };

  const points = Array.from({ length: PROFILE_SAMPLE_COUNT }, (_, column) => {
    const x = column * SOURCE_SIZE / PROFILE_INTERVALS;
    const normalizedX = (x - 0.02 * drift(0.3, 3 * depth) * SOURCE_SIZE - SOURCE_SIZE / 2) / SOURCE_SIZE;
    const silhouette = outlineHeight(normalizedX);
    if (silhouette <= 0) return { x, y: SOURCE_BASELINE };

    const ridgeValue = 0.5 + 0.5 * ridge(x / (0.22 * SOURCE_SIZE), id / 30);
    const detailValue = detail(x / (0.07 * SOURCE_SIZE), id / 7);
    const grainValue = grain(x / (0.015 * SOURCE_SIZE), id / 3);
    const creaseValue = (1 - Math.abs(crease(x / (0.12 * SOURCE_SIZE), id / 18))) * (1 - Math.pow(silhouette, 3));
    const variation = 0.74 + 0.18 * ridgeValue + 0.08 * creaseValue + 0.04 * detailValue + 0.02 * grainValue;
    const notchValue = (id <= COVERAGE_FEATURE.slice ? 1 - featureMask(COVERAGE_FEATURE, x) : 1)
      * (1 - 0.35 * depth) * clampSmoothstep(0.15, 0.21, notch(x / (0.11 * SOURCE_SIZE), id / 9));
    let height = (SOURCE_BASELINE - SOURCE_SIZE * 0.06) * adjustedDepth * silhouette * variation * (1 - 0.13 * notchValue);
    if (id < COVERAGE_FEATURE.slice) {
      const progress = 1 - (COVERAGE_FEATURE.slice - id) / COVERAGE_FEATURE.slice;
      height -= (SOURCE_BASELINE - SOURCE_SIZE * 0.06) * COVERAGE_FEATURE.depth * featureMask(COVERAGE_FEATURE, x) * (0.15 + 0.85 * progress * progress);
    }
    return { x, y: SOURCE_BASELINE - Math.max(0, height) };
  });

  return {
    id,
    depth,
    points,
    baseline: SOURCE_BASELINE,
    color: face.color,
    alpha: face.alpha,
    isSelected: id === SELECTED_SLICE_ID,
    gritOffset,
    soft: id % 3 === 0,
    revealDelay: revealRandom() * 0.35,
    revealSweep: 1 + revealRandom() * (1.45 - 1),
  };
}

const descendingSlices: Slice[] = [];
const faceRandom = createSeededRandom(101 * 21 + 23);
const gritRandom = createSeededRandom(101 * 21 + 9);
const revealRandom = createSeededRandom(101 * 21 + 31);
for (let id = SLICE_COUNT - 1; id >= 0; id -= 1) descendingSlices.push(makeSlice(id, faceRandom, gritRandom, revealRandom));
export const sourceRenderOrderSlices: readonly Slice[] = [...descendingSlices];
export const slices: Slice[] = descendingSlices.reverse();
export const mountainSourceSlices = slices;
export const mountainSlices = slices;
const foundSelectedSlice = slices.find((slice) => slice.id === SELECTED_SLICE_ID);
if (foundSelectedSlice === undefined) throw new Error(`Missing selected profile ${SELECTED_SLICE_ID}`);
export const selectedSlice = foundSelectedSlice;
export const profile = selectedSlice.points;

const GRID_TOTAL_WIDTH = GRID_COLUMNS + (GRID_COLUMNS - 1) * GRID_GAP_X;
const GRID_TOTAL_HEIGHT = GRID_ROWS + (GRID_ROWS - 1) * GRID_GAP_Y;
export const gridCells: GridCell[] = Array.from({ length: SLICE_COUNT }, (_, id) => {
  const column = id % GRID_COLUMNS;
  const row = Math.floor(id / GRID_COLUMNS);
  return {
    id,
    column,
    row,
    x: (column * (1 + GRID_GAP_X) + SOURCE_SIZE / (2 * ART_WIDTH)) / GRID_TOTAL_WIDTH,
    y: (row * (1 + GRID_GAP_Y) + 1) / GRID_TOTAL_HEIGHT,
  };
});

export const spanBounds = [0, 0.17, 0.33, 0.51, 0.66, 0.84, 1] as const;
const chartNoise = createSeededRandom(101 * 21 + 41);
let chartDrift = 0;
const chartMaximumElevation = Math.max(...selectedSlice.points.map(({ y }) => SOURCE_BASELINE - y));
export const chartContour: Point[] = selectedSlice.points.map(({ y }, index) => {
  let noise = 0;
  for (let sample = 0; sample < 4; sample += 1) noise += chartNoise();
  noise = (noise - 2) * 1.73;
  chartDrift += noise * 0.012 * chartMaximumElevation - chartDrift * 0.04;
  const smoothing = (SOURCE_BASELINE - y) * 0.86 + 0.14 * chartMaximumElevation + chartDrift;
  return { x: index * SOURCE_SIZE / PROFILE_INTERVALS, y: SOURCE_BASELINE - Math.max(0, smoothing) };
});

export function chartPointAt(normalizedX: number): Point {
  const sourceX = Math.max(0, Math.min(1, normalizedX)) * ART_WIDTH;
  const sample = Math.max(0, Math.min(PROFILE_INTERVALS, Math.round(sourceX * PROFILE_INTERVALS / SOURCE_SIZE)));
  const contourPoint = chartContour[sample];
  if (contourPoint === undefined) throw new Error(`Missing chart sample ${sample}`);
  return { x: sourceX, y: contourPoint.y };
}

export function chartPointAtLinear(normalizedX: number): Point {
  const sourceX = Math.max(0, Math.min(1, normalizedX)) * ART_WIDTH;
  const position = sourceX * PROFILE_INTERVALS / SOURCE_SIZE;
  const sample = Math.max(0, Math.min(PROFILE_INTERVALS - 1, Math.floor(position)));
  const fraction = position - sample;
  const left = chartContour[sample];
  const right = chartContour[sample + 1];
  if (left === undefined || right === undefined) throw new Error(`Missing chart interval ${sample}`);
  return { x: sourceX, y: left.y + (right.y - left.y) * fraction };
}

export const chartSpans: Point[][] = spanBounds.slice(0, -1).map((start, span) => {
  const left = start * ART_WIDTH;
  const right = spanBounds[span + 1]! * ART_WIDTH;
  const first = Math.max(0, Math.floor(left * PROFILE_INTERVALS / SOURCE_SIZE));
  const last = Math.min(PROFILE_INTERVALS, Math.ceil(right * PROFILE_INTERVALS / SOURCE_SIZE));
  return [chartPointAtLinear(left / ART_WIDTH), ...chartContour.slice(first + 1, last).map(({ x, y }) => ({ x, y })), chartPointAtLinear(right / ART_WIDTH)];
});

export function mixColor(hex: string, opacity: number): string {
  const number = Number.parseInt(hex.slice(1), 16);
  const red = number >> 16;
  const green = (number >> 8) & 255;
  const blue = number & 255;
  return `rgba(${red}, ${green}, ${blue}, ${opacity})`;
}
