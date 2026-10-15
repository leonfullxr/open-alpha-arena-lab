import { ART_WIDTH, SOURCE_SIZE, chartPointAt, spanBounds, type Point } from './geometry';

export const LATTICE_TETHER_SEGMENTS = 24;
export const LATTICE_SPAN_SWEEP = 0.1;
export const LATTICE_DEPARTURE_SPREAD = 0.24;

export const TASK_FAMILY_ORDER = [
  'Forecasting',
  'Risk management',
  'Portfolio management',
  'Systematic trading',
  'Backtesting & simulation',
  'Execution',
] as const;

type Vector3 = readonly [number, number, number];
export type ProjectedPoint = Point;
export type LatticeCube = {
  id: number;
  cubeIndex: number;
  familyIndex: number;
  withinFamily: number;
  center: ProjectedPoint;
  width: number;
  depth: number;
  faces: readonly (readonly ProjectedPoint[])[];
  edges: readonly (readonly ProjectedPoint[])[];
  tethers: readonly LatticeTether[];
};
export type LatticeTether = { id: number; cubeIndex: number; familyIndex: number; depth: number; from: ProjectedPoint; to: ProjectedPoint };
export type LatticeDrawOp =
  | { kind: 'cube'; depth: number; cubeIndex: number }
  | { kind: 'tether'; depth: number; tetherIndex: number };
export type ChartFlight = {
  cubeIndex: number;
  familyIndex: number;
  withinFamily: number;
  start: ProjectedPoint;
  side: number;
  depth: number;
  column: number;
  columnCount: number;
  columnStart: number;
  delay: number;
};
export type ChartFamilyColumns = { familyIndex: number; columnEdges: readonly number[] };

const familyBoxes = [
  { name: 'Portfolio management', min: [0, 0, 0], max: [8, 5, 4] },
  { name: 'Systematic trading', min: [0, 0, 4], max: [5, 5, 8] },
  { name: 'Forecasting', min: [0, 5, 0], max: [8, 8, 4] },
  { name: 'Risk management', min: [0, 5, 4], max: [5, 8, 8] },
  { name: 'Backtesting & simulation', min: [5, 0, 4], max: [8, 5, 8] },
  { name: 'Execution', min: [5, 5, 4], max: [8, 8, 8] },
] as const satisfies readonly { name: (typeof TASK_FAMILY_ORDER)[number]; min: Vector3; max: Vector3 }[];

const cubeEdges = [
  [[-1, 1, -1], [-1, 1, 1]], [[1, 1, 1], [1, 1, -1]], [[-1, -1, 1], [-1, -1, -1]], [[1, -1, -1], [1, -1, 1]],
  [[-1, 1, 1], [-1, -1, 1]], [[1, 1, 1], [-1, 1, 1]], [[-1, -1, 1], [1, -1, 1]], [[1, -1, 1], [1, 1, 1]],
  [[1, 1, -1], [1, -1, -1]], [[-1, 1, -1], [1, 1, -1]], [[1, -1, -1], [-1, -1, -1]], [[-1, -1, -1], [-1, 1, -1]],
] as const satisfies readonly (readonly [Vector3, Vector3])[];

const cubeFaces = [
  [[-1, 1, -1], [1, 1, -1], [1, 1, 1], [-1, 1, 1]],
  [[1, -1, -1], [1, 1, -1], [1, 1, 1], [1, -1, 1]],
  [[-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]],
] as const satisfies readonly (readonly Vector3[])[];

function createSeededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    let value = state = (state + 0x6d2b79f5) >>> 0;
    value = Math.imul(value ^ value >>> 15, 1 | value);
    value ^= value + Math.imul(value ^ value >>> 7, 61 | value);
    return ((value ^ value >>> 14) >>> 0) / 0x100000000;
  };
}

function normalize(vector: Vector3): Vector3 {
  const magnitude = Math.hypot(...vector);
  return [vector[0] / magnitude, vector[1] / magnitude, vector[2] / magnitude];
}

function dot(left: Vector3, right: Vector3): number {
  return left[0] * right[0] + left[1] * right[1] + left[2] * right[2];
}

function cross(left: Vector3, right: Vector3): Vector3 {
  return [
    left[1] * right[2] - left[2] * right[1],
    left[2] * right[0] - left[0] * right[2],
    left[0] * right[1] - left[1] * right[0],
  ];
}

const view = normalize([60, 50, 60]);
const screenRight = normalize([view[2], 0, -view[0]]);
const screenUp = cross(view, screenRight);

function project(point: Vector3): ProjectedPoint {
  return { x: 0.5 + dot(point, screenRight) / 64, y: 0.5 - dot(point, screenUp) / 64 };
}

function makeLattice(): { cubes: LatticeCube[]; tethers: LatticeTether[]; drawOps: LatticeDrawOp[] } {
  const unsorted: { cube: Omit<LatticeCube, 'id' | 'cubeIndex' | 'withinFamily'>; depth: number; tethers: Omit<LatticeTether, 'id' | 'cubeIndex' | 'familyIndex'>[] }[] = [];
  let randomIndex = 0;

  for (const familyBox of familyBoxes) {
    const familyIndex = TASK_FAMILY_ORDER.indexOf(familyBox.name);
    const midpoint: Vector3 = [
      (familyBox.min[0] + familyBox.max[0]) / 2 - 4,
      (familyBox.min[1] + familyBox.max[1]) / 2 - 4,
      (familyBox.min[2] + familyBox.max[2]) / 2 - 4,
    ];

    for (let x = familyBox.min[0]; x < familyBox.max[0]; x += 1) {
      for (let y = familyBox.min[1]; y < familyBox.max[1]; y += 1) {
        for (let z = familyBox.min[2]; z < familyBox.max[2]; z += 1) {
          const positionRandom = createSeededRandom(31 * randomIndex + 7);
          const edgeRandom = createSeededRandom(randomIndex + 1);
          randomIndex += 1;
          const center: Vector3 = [
            (x + 0.5 - 4 + 0.5 * midpoint[0]) * 4 + (positionRandom() - 0.5) * 1.8,
            (y + 0.5 - 4 + 0.5 * midpoint[1]) * 4 + (positionRandom() - 0.5) * 1.8,
            (z + 0.5 - 4 + 0.5 * midpoint[2]) * 4 + (positionRandom() - 0.5) * 1.8,
          ];
          const at = (offset: Vector3): Vector3 => [center[0] + offset[0], center[1] + offset[1], center[2] + offset[2]];
          const faces = cubeFaces.map((face) => face.map((corner) => project(at([0.49 * corner[0], 0.49 * corner[1], 0.49 * corner[2]]))));
          const edges = cubeEdges.flatMap(([fromCorner, toCorner]) => {
            const from: Vector3 = [0.49 * fromCorner[0], 0.49 * fromCorner[1], 0.49 * fromCorner[2]];
            const to: Vector3 = [0.49 * toCorner[0], 0.49 * toCorner[1], 0.49 * toCorner[2]];
            const direction = normalize([to[0] - from[0], to[1] - from[1], to[2] - from[2]]);
            const lateral = [direction[1], direction[2], direction[0]] as const;
            const normal = cross(direction, lateral);
            const samples: ProjectedPoint[] = [];
            for (let step = 0; step <= 4; step += 1) {
              const progress = -0.02 + step / 4 * 1.04;
              const jitter = 0.011 * (step === 0 || step === 4 ? 0.3 : 1);
              const side = (edgeRandom() - 0.5) * 2 * jitter;
              const depth = (edgeRandom() - 0.5) * 2 * jitter;
              const point: Vector3 = [
                from[0] + (to[0] - from[0]) * progress + lateral[0] * side + normal[0] * depth,
                from[1] + (to[1] - from[1]) * progress + lateral[1] * side + normal[1] * depth,
                from[2] + (to[2] - from[2]) * progress + lateral[2] * side + normal[2] * depth,
              ];
              samples.push(project(at(point)));
            }
            return fromCorner.every((coordinate) => coordinate < 0) || toCorner.every((coordinate) => coordinate < 0)
              ? []
              : [samples];
          });
          const projectedXs = faces.flatMap((face) => face.map((point) => point.x));
          const projectedCenter = project(center);
          const cubeTethers: Omit<LatticeTether, 'id' | 'cubeIndex' | 'familyIndex'>[] = [];
          const originScale = Math.min(...center.map((coordinate) => 0.49 / Math.abs(coordinate)));
          if (originScale < 1) {
            const end: Vector3 = [center[0] * (1 - originScale), center[1] * (1 - originScale), center[2] * (1 - originScale)];
            const tetherPoint = (ratio: number): Vector3 => [end[0] * (1 - ratio), end[1] * (1 - ratio), end[2] * (1 - ratio)];
            for (let segment = 0; segment < LATTICE_TETHER_SEGMENTS; segment += 1) {
              const midpointRatio = (segment + 0.5) / LATTICE_TETHER_SEGMENTS;
              cubeTethers.push({
                depth: dot(tetherPoint(midpointRatio), view),
                from: project(tetherPoint(segment / LATTICE_TETHER_SEGMENTS)),
                to: project(tetherPoint((segment + 1) / LATTICE_TETHER_SEGMENTS)),
              });
            }
          }
          unsorted.push({
            cube: {
              familyIndex,
              center: projectedCenter,
              width: Math.max(...projectedXs) - Math.min(...projectedXs),
              depth: dot(center, view),
              faces,
              edges,
              tethers: [],
            },
            depth: dot(center, view),
            tethers: cubeTethers,
          });
        }
      }
    }
  }

  const depthOrdered = [...unsorted].sort((left, right) => left.depth - right.depth);
  const cubes: LatticeCube[] = depthOrdered.map(({ cube, tethers }, id) => ({
    ...cube,
    id,
    cubeIndex: id,
    withinFamily: 0,
    tethers: tethers.map((tether) => ({ ...tether, id: 0, cubeIndex: id, familyIndex: cube.familyIndex })),
  }));
  for (let familyIndex = 0; familyIndex < TASK_FAMILY_ORDER.length; familyIndex += 1) {
    const orderedFamilyCubes = cubes.filter((cube) => cube.familyIndex === familyIndex).sort((left, right) => left.center.x - right.center.x);
    orderedFamilyCubes.forEach((cube, withinFamily) => { cube.withinFamily = withinFamily; });
  }
  const tethers: LatticeTether[] = [];
  for (const cube of cubes) {
    for (const tether of cube.tethers) {
      tether.id = tethers.length;
      tethers.push(tether);
    }
  }
  const drawOps: LatticeDrawOp[] = [];
  for (const cube of cubes) {
    drawOps.push({ kind: 'cube', cubeIndex: cube.cubeIndex, depth: cube.depth });
    for (const tether of cube.tethers) drawOps.push({ kind: 'tether', tetherIndex: tether.id, depth: tether.depth });
  }
  drawOps.sort((left, right) => left.depth - right.depth);
  return { cubes, tethers, drawOps };
}

const lattice = makeLattice();
export const LATTICE_CUBES = lattice.cubes;
export const LATTICE_TETHERS = lattice.tethers;
export const LATTICE_DRAW_OPS = lattice.drawOps;

type ChartCandidate = { x: number; y: number; side: number; column: number; depth: number };
const flightRandom = createSeededRandom(37 * 21 + 11);
const familyCubes = Array.from({ length: TASK_FAMILY_ORDER.length }, (_, familyIndex) =>
  LATTICE_CUBES.filter((cube) => cube.familyIndex === familyIndex).sort((left, right) => left.center.x - right.center.x),
);
const flightsByCube = new Map<number, ChartFlight>();
export const chartFamilyColumns: ChartFamilyColumns[] = [];

for (let familyIndex = 0; familyIndex < TASK_FAMILY_ORDER.length; familyIndex += 1) {
  const cubes = familyCubes[familyIndex]!;
  const spanStart = spanBounds[familyIndex]! * ART_WIDTH;
  const spanWidth = (spanBounds[familyIndex + 1]! - spanBounds[familyIndex]!) * ART_WIDTH;
  const chartY = (sourceX: number) => chartPointAt(sourceX / ART_WIDTH).y;
  const candidatesForColumns = (columnCount: number): ChartCandidate[] => {
    const columnWidth = spanWidth / columnCount;
    const candidates: ChartCandidate[] = [];
    for (let column = 0; column < columnCount; column += 1) {
      const x = spanStart + (column + 0.5) * columnWidth;
      const top = Math.max(chartY(x - columnWidth / 2), chartY(x), chartY(x + columnWidth / 2));
      for (let row = 0; SOURCE_SIZE - (row + 1) * columnWidth >= top; row += 1) {
        const y = SOURCE_SIZE - (row + 0.5) * columnWidth;
        candidates.push({ x, y, side: columnWidth, column, depth: y - top });
      }
    }
    return candidates;
  };

  let columnCount = 1;
  let candidates = candidatesForColumns(columnCount);
  while (candidates.length < cubes.length) {
    columnCount += 1;
    candidates = candidatesForColumns(columnCount);
  }
  candidates.sort((left, right) => right.depth - left.depth);
  const selectedCandidates = candidates.slice(0, cubes.length).sort((left, right) => left.x - right.x || left.y - right.y);
  cubes.forEach((cube, withinFamily) => {
    const start = selectedCandidates[withinFamily]!;
    const columnStart = start.column / columnCount * LATTICE_SPAN_SWEEP;
    flightsByCube.set(cube.cubeIndex, {
      cubeIndex: cube.cubeIndex,
      familyIndex,
      withinFamily,
      start: { x: start.x / SOURCE_SIZE, y: start.y / SOURCE_SIZE },
      side: start.side / SOURCE_SIZE,
      depth: start.depth,
      column: start.column,
      columnCount,
      columnStart,
      delay: columnStart + LATTICE_DEPARTURE_SPREAD * flightRandom(),
    });
  });
  chartFamilyColumns.push({
    familyIndex,
    columnEdges: Array.from({ length: columnCount + 1 }, (_, column) => (spanStart + column / columnCount * spanWidth) / SOURCE_SIZE),
  });
}

export const CHART_FLIGHTS: readonly ChartFlight[] = LATTICE_CUBES.map((cube) => {
  const flight = flightsByCube.get(cube.cubeIndex);
  if (flight === undefined) throw new Error(`Missing chart flight for lattice cube ${cube.cubeIndex}`);
  return flight;
});
