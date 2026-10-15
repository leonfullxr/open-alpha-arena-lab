export const ART_WIDTH = 1183;
export const ART_HEIGHT = 860;
export const CHART_TOP = 0;
export const CHART_BASE = 810;
export const SLICE_COUNT = 220;
export const FAMILY_COLORS = ['#8bc6a1', '#ec9ba9', '#f2d474', '#85b4cd', '#ee9a76', '#a6a7a2'] as const;
export const FAMILY_NAMES = ['Market data', 'Prompts', 'Risk checks', 'Execution', 'Accounting', 'Evaluation'] as const;
const ridgeColors = [FAMILY_COLORS[1], FAMILY_COLORS[1], FAMILY_COLORS[3], FAMILY_COLORS[0], FAMILY_COLORS[3]] as const;
const mountainBands = [
  [12, 13, '#bb739b'],
  [25, 29, '#438b75'],
  [43, 45, '#7f68a5'],
  [59, 63, '#44779c'],
  [77, 78, '#bb739b'],
  [94, 98, '#44779c'],
  [111, 113, '#bb739b'],
  [127, 129, '#438b75'],
  [137, 139, '#df975e'],
  [155, 159, '#438b75'],
  [176, 177, '#7f68a5'],
  [191, 193, '#bb739b'],
] as const satisfies readonly (readonly [number, number, string])[];

export type Point = { x: number; y: number };
export type Slice = { id: number; depth: number; points: Point[]; baseline: number; color: string | null };

function seeded(index: number): number {
  const value = Math.sin(index * 127.1 + 311.7) * 43758.5453;
  return value - Math.floor(value);
}

export const profile: Point[] = Array.from({ length: 121 }, (_, index) => {
  const x = index / 120;
  const envelope = Math.pow(Math.max(0, Math.sin(Math.PI * x)), 0.72);
  const mainPeak = 0.86 * Math.exp(-(((x - 0.61) / 0.18) ** 2));
  const westernRidge = 0.3 * Math.exp(-(((x - 0.34) / 0.12) ** 2));
  const easternRidge = 0.21 * Math.exp(-(((x - 0.84) / 0.13) ** 2));
  const texture = 0.055 * Math.sin(index * 0.21) + 0.04 * Math.sin(index * 0.63 + 1.2) + (seeded(index) - 0.5) * 0.045;
  const elevation = envelope * (0.14 + mainPeak + westernRidge + easternRidge + texture);
  return { x: x * ART_WIDTH, y: 860 - elevation * 720 };
});

export const slices: Slice[] = Array.from({ length: SLICE_COUNT }, (_, id) => {
  const depth = id / (SLICE_COUNT - 1);
  const offsetX = (depth - 0.5) * 94;
  const baseline = 860;
  const scaleX = 0.82 + depth * 0.3;
  const scaleY = 1.08 * Math.pow(1 - depth, 0.9) + 0.015;
  const points = profile.map((point, pointIndex) => ({
    x: ART_WIDTH / 2 + (point.x - ART_WIDTH / 2) * scaleX + offsetX + Math.sin(pointIndex * 0.08 + id * 0.04) * 2.4,
    y: baseline + (point.y - 860) * scaleY + Math.sin(pointIndex * 0.19 + id * 0.12) * 2.1 * scaleY * Math.sin(Math.PI * pointIndex / 120),
  }));
  const family = Math.floor(seeded(id + 510) * ridgeColors.length);
  const color = id === 137 ? FAMILY_COLORS[4]! : id % 17 === 5 || id % 37 === 17 ? ridgeColors[family]! : null;
  return { id, depth, points, baseline, color };
});

export const selectedSlice = slices[137]!;

function mountainColor(id: number): string | null {
  const band = mountainBands.find(([start, end]) => id >= start && id <= end);
  return band?.[2] ?? null;
}

const mountainOutline = [
  [0, 0.997], [0.0625, 0.89], [0.125, 0.749], [0.1875, 0.625], [0.25, 0.520],
  [0.3125, 0.286], [0.375, 0.175], [0.4375, 0.031], [0.46875, 0.054], [0.5, 0.033],
  [0.53125, 0.007], [0.5625, 0.011], [0.625, 0.171], [0.6875, 0.278], [0.75, 0.319],
  [0.8125, 0.417], [0.875, 0.559], [0.9375, 0.773], [1, 1],
] as const;

function mountainProfileHeight(x: number): number {
  const index = mountainOutline.findIndex(([end]) => x <= end);
  const nextIndex = Math.max(1, index);
  const [startX, startY] = mountainOutline[nextIndex - 1]!;
  const [endX, endY] = mountainOutline[nextIndex]!;
  const linear = (x - startX) / (endX - startX);
  const blend = linear * linear * (3 - 2 * linear);
  return 1 - (startY + (endY - startY) * blend);
}

export const mountainSourceSlices: Slice[] = Array.from({ length: SLICE_COUNT }, (_, id) => {
  const depth = id / (SLICE_COUNT - 1);
  const phase = depth * Math.PI * 2;
  const baseline = ART_HEIGHT;
  const depthScale = Math.pow(1 - depth, 0.9);
  const points = Array.from({ length: 121 }, (_, pointIndex) => {
    const x = pointIndex / 120;
    const depthOffset = Math.sin(Math.PI * depth);
    const shiftedX = x + 0.09 * depthOffset * Math.exp(-(((x - 0.52) / 0.3) ** 2))
      - (0.012 * Math.sin(phase * 0.69) + 0.018 * Math.sin(phase * 1.43 + x * 5)) * depthOffset * Math.sin(Math.PI * x);
    const broadFace = mountainProfileHeight(shiftedX) * depthScale;
    const leftCenter = 0.4375 + 0.016 * Math.sin(phase * 0.91) * depthOffset;
    const rightCenter = 0.53125 + 0.019 * Math.sin(phase * 0.69 + 0.8) * depthOffset;
    const leftRidge = 0.075 * Math.sin(phase * 0.91) * depthOffset * Math.exp(-(((shiftedX - leftCenter) / 0.07) ** 2));
    const rightRidge = 0.085 * Math.sin(phase * 0.69 + 0.8) * depthOffset * Math.exp(-(((shiftedX - rightCenter) / 0.075) ** 2));
    const middleFace = 0.04 * Math.sin(phase * 0.59) * depthOffset * Math.exp(-(((shiftedX - 0.5) / 0.24) ** 2));
    const forwardEnvelope = Math.exp(-(((depth - 0.35) / 0.23) ** 2));
    const forwardRidge = 0.14 * forwardEnvelope * Math.exp(-(((shiftedX - 0.46) / 0.09) ** 2));
    const shoulders = 0.035 * (Math.cos(phase) - 1) * depthOffset
      * (Math.exp(-(((shiftedX - 0.25) / 0.14) ** 2)) + Math.exp(-(((shiftedX - 0.75) / 0.15) ** 2)));
    const roughness = (Math.sin(pointIndex * 0.43 + phase * 1.9) + 0.55 * Math.sin(pointIndex * 0.92 - phase * 1.2) + (seeded(id * 121 + pointIndex) - 0.5) * 0.6)
      * 0.012 * depthOffset * Math.sin(Math.PI * x);
    const elevation = Math.max(0, broadFace + leftRidge + rightRidge + middleFace + forwardRidge + shoulders + roughness);
    const horizontalScale = 0.08 * depth * depthOffset;
    const horizontalShift = 26 * Math.sin(phase) * depthOffset;
    const projectedX = x * ART_WIDTH
      + (x - 0.5) * ART_WIDTH * horizontalScale * Math.sin(Math.PI * x)
      + horizontalShift * Math.sin(Math.PI * x);
    const projectedY = baseline - elevation * ART_HEIGHT
      + Math.sin(pointIndex * 0.19 + id * 0.12) * 2.2 * depthOffset * Math.sin(Math.PI * x);
    return { x: projectedX, y: projectedY };
  });
  return { id, depth, points, baseline, color: mountainColor(id) };
});

export const mountainSlices: Slice[] = mountainSourceSlices.slice(0, -1).flatMap((left, index) => {
  const right = mountainSourceSlices[index + 1]!;
  return Array.from({ length: 3 }, (_, segment) => {
    const fraction = segment / 3;
    return {
      id: left.id + fraction,
      depth: left.depth + (right.depth - left.depth) * fraction,
      baseline: left.baseline + (right.baseline - left.baseline) * fraction,
      color: left.color,
      points: left.points.map((point, pointIndex) => {
        const next = right.points[pointIndex]!;
        return {
          x: point.x + (next.x - point.x) * fraction,
          y: point.y + (next.y - point.y) * fraction,
        };
      }),
    };
  });
}).concat(mountainSourceSlices.slice(-1));

export const spanBounds = [0, 0.17, 0.33, 0.51, 0.66, 0.84, 1] as const;
const selectedYMin = Math.min(...selectedSlice.points.map((point) => point.y));
const selectedYMax = Math.max(...selectedSlice.points.map((point) => point.y));

export function profileAt(x: number): Point {
  const target = Math.max(0, Math.min(1, x)) * (profile.length - 1);
  const low = Math.floor(target);
  const high = Math.min(profile.length - 1, low + 1);
  const blend = target - low;
  const source = selectedSlice.points;
  const sourceY = source[low]!.y * (1 - blend) + source[high]!.y * blend;
  return { x: x * ART_WIDTH, y: sourceY };
}

export function chartPointAt(x: number): Point {
  const sourceX = 0.08 + x * 0.92;
  const point = profileAt(sourceX);
  const elevation = (selectedYMax - point.y) / Math.max(1, selectedYMax - selectedYMin);
  const height = 0.68 * elevation + 0.12 * x + 0.025;
  return { x: x * ART_WIDTH, y: CHART_BASE - height * (CHART_BASE - CHART_TOP) };
}

export function mixColor(hex: string, opacity: number): string {
  const number = Number.parseInt(hex.slice(1), 16);
  const red = number >> 16;
  const green = (number >> 8) & 255;
  const blue = number & 255;
  return `rgba(${red}, ${green}, ${blue}, ${opacity})`;
}
