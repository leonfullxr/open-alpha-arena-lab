export const ART_WIDTH = 1183;
export const ART_HEIGHT = 860;
export const SLICE_COUNT = 220;
export const FAMILY_COLORS = ['#46a758', '#e5484d', '#ffc53d', '#2e7db5', '#f26a2e', '#63635e'] as const;
export const FAMILY_NAMES = ['Market data', 'Prompts', 'Risk checks', 'Execution', 'Accounting', 'Evaluation'] as const;

export type Point = { x: number; y: number };
export type Slice = { id: number; depth: number; points: Point[]; baseline: number; color: string | null };

function seeded(index: number): number {
  const value = Math.sin(index * 127.1 + 311.7) * 43758.5453;
  return value - Math.floor(value);
}

export const profile: Point[] = Array.from({ length: 121 }, (_, index) => {
  const x = index / 120;
  const envelope = Math.pow(Math.max(0, Math.sin(Math.PI * x)), 0.72);
  const ridge = 0.58 + 0.18 * Math.sin(index * 0.21) + 0.12 * Math.sin(index * 0.63 + 1.2) + (seeded(index) - 0.5) * 0.16;
  return { x: x * ART_WIDTH, y: 620 - envelope * Math.max(95, ridge * 480) };
});

export const slices: Slice[] = Array.from({ length: SLICE_COUNT }, (_, id) => {
  const depth = id / (SLICE_COUNT - 1);
  const offsetX = (depth - 0.5) * 120;
  const offsetY = (0.5 - depth) * 114;
  const points = profile.map((point, pointIndex) => ({
    x: point.x + offsetX + Math.sin(pointIndex * 0.08 + id * 0.04) * 2.4,
    y: point.y + offsetY + Math.sin(pointIndex * 0.19 + id * 0.12) * 2.1,
  }));
  const family = Math.floor(seeded(id + 510) * FAMILY_COLORS.length);
  const color = id % 23 === 7 || id % 41 === 13 ? FAMILY_COLORS[family]! : null;
  return { id, depth, points, baseline: 720 + offsetY, color };
});

export const selectedSlice = slices[137]!;
export const spanBounds = [0, 0.17, 0.33, 0.51, 0.66, 0.84, 1] as const;

export function profileAt(x: number): Point {
  const target = Math.max(0, Math.min(1, x)) * (profile.length - 1);
  const low = Math.floor(target);
  const high = Math.min(profile.length - 1, low + 1);
  const blend = target - low;
  const source = selectedSlice.points;
  return { x: x * ART_WIDTH, y: source[low]!.y * (1 - blend) + source[high]!.y * blend };
}

export function mixColor(hex: string, opacity: number): string {
  const number = Number.parseInt(hex.slice(1), 16);
  const red = number >> 16;
  const green = (number >> 8) & 255;
  const blue = number & 255;
  return `rgba(${red}, ${green}, ${blue}, ${opacity})`;
}
