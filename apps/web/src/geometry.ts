export const ART_WIDTH = 1183;
export const ART_HEIGHT = 860;
export const CHART_TOP = 0;
export const CHART_BASE = 810;
export const SLICE_COUNT = 220;
export const FAMILY_COLORS = ['#8bc6a1', '#ec9ba9', '#f2d474', '#85b4cd', '#ee9a76', '#a6a7a2'] as const;
export const FAMILY_NAMES = ['Market data', 'Prompts', 'Risk checks', 'Execution', 'Accounting', 'Evaluation'] as const;
const ridgeColors = [FAMILY_COLORS[1], FAMILY_COLORS[1], FAMILY_COLORS[3], FAMILY_COLORS[0], FAMILY_COLORS[3]] as const;

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
