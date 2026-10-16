import { LATTICE_CUBES, type LatticeCube } from './lattice-geometry';

export const LOGO_SQUARE_PITCH = 27.9;
export const LOGO_SQUARE_PAD = 1;
export const LOGO_HANDOFF = 0.03;
export const LOGO_SWEEP = 0.26;
export const LOGO_DELAY_JITTER = 0.12;
export const LOGO_LANDING_JITTER = 0.06;
export const LOGO_CUBE_FLIGHT = 0.45;
export const LOGO_ROW_FADE = 0.03;

export const LOGO_FAMILY_RGBS = [
  [11, 11, 12],
  [11, 11, 12],
  [11, 11, 12],
  [0, 161, 94],
  [0, 161, 94],
  [0, 161, 94],
] as const;

export type LogoSquare = {
  x: number;
  y: number;
  width: number;
  height: number;
  familyIndex: number;
  rgb: readonly [number, number, number];
};

export type LogoBitmap = { data: ArrayLike<number>; width: number; height: number };
export type LogoFlightDirection = 'outbound' | 'inbound';
export type LogoFlight = {
  cubeIndex: number;
  familyIndex: number;
  cube: LatticeCube;
  squares: readonly LogoSquare[];
  delay: number;
  landAt: number;
  settleFrom: number;
};
export type LogoBand = { top: number; bottom: number; landAt: number };
export type LogoPlan = {
  width: number;
  height: number;
  direction: LogoFlightDirection;
  flights: readonly LogoFlight[];
  bands: readonly LogoBand[];
};

type MutableSquare = {
  x: number;
  y: number;
  width: number;
  height: number;
  familyIndex: number;
  rgb: [number, number, number];
};

export function segmentLogoSquares(bitmap: LogoBitmap): LogoSquare[] {
  const { data, width, height } = bitmap;
  if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0) {
    throw new RangeError('Logo bitmap dimensions must be positive integers');
  }

  const pixelCount = width * height;
  if (data.length < pixelCount * 4) throw new RangeError('Logo bitmap data is shorter than its dimensions');

  const familyAtPixel = new Int8Array(pixelCount).fill(-1);
  for (let pixel = 0; pixel < pixelCount; pixel += 1) {
    const offset = pixel * 4;
    if (data[offset + 3] < 128) continue;

    let nearestFamily = 0;
    let nearestDistance = Number.POSITIVE_INFINITY;
    for (let familyIndex = 0; familyIndex < LOGO_FAMILY_RGBS.length; familyIndex += 1) {
      const color = LOGO_FAMILY_RGBS[familyIndex];
      const red = data[offset] - color[0];
      const green = data[offset + 1] - color[1];
      const blue = data[offset + 2] - color[2];
      const distance = red * red + green * green + blue * blue;
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestFamily = familyIndex;
      }
    }
    const x = pixel % width;
    const y = (pixel - x) / width;
    const isBracket = nearestFamily < 3;
    const band = Math.min(2, Math.floor((isBracket ? y / height : x / width) * 3));
    familyAtPixel[pixel] = (isBracket ? 0 : 3) + band;
  }

  const visited = new Uint8Array(pixelCount);
  const stack = new Int32Array(pixelCount);
  const componentPixels = new Int32Array(pixelCount);
  const squares: MutableSquare[] = [];
  let stackLength = 0;

  const pushNeighbor = (index: number, familyIndex: number): void => {
    if (index < 0 || index >= pixelCount || visited[index] || familyAtPixel[index] !== familyIndex) return;
    visited[index] = 1;
    stack[stackLength] = index;
    stackLength += 1;
  };

  for (let seed = 0; seed < pixelCount; seed += 1) {
    const familyIndex = familyAtPixel[seed];
    if (familyIndex < 0 || visited[seed]) continue;

    stackLength = 1;
    stack[0] = seed;
    visited[seed] = 1;
    let componentLength = 0;
    let minX = width;
    let maxX = -1;
    let minY = height;
    let maxY = -1;

    while (stackLength > 0) {
      stackLength -= 1;
      const pixel = stack[stackLength];
      componentPixels[componentLength] = pixel;
      componentLength += 1;

      const x = pixel % width;
      const y = (pixel - x) / width;
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);

      if (x > 0) pushNeighbor(pixel - 1, familyIndex);
      if (x < width - 1) pushNeighbor(pixel + 1, familyIndex);
      pushNeighbor(pixel - width, familyIndex);
      pushNeighbor(pixel + width, familyIndex);
    }

    if (componentLength < 24) continue;
    const componentWidth = maxX - minX + 1;
    const componentHeight = maxY - minY + 1;
    const columns = Math.max(1, Math.round(componentWidth / LOGO_SQUARE_PITCH));
    const rows = Math.max(1, Math.round(componentHeight / LOGO_SQUARE_PITCH));
    const tileWidth = componentWidth / columns;
    const tileHeight = componentHeight / rows;
    const tileCount = columns * rows;
    const redSums = new Float64Array(tileCount);
    const greenSums = new Float64Array(tileCount);
    const blueSums = new Float64Array(tileCount);
    const tilePixels = new Uint32Array(tileCount);

    for (let index = 0; index < componentLength; index += 1) {
      const pixel = componentPixels[index];
      const x = pixel % width;
      const y = (pixel - x) / width;
      const column = Math.min(columns - 1, Math.floor((x - minX) / tileWidth));
      const row = Math.min(rows - 1, Math.floor((y - minY) / tileHeight));
      const tile = row * columns + column;
      const offset = pixel * 4;
      redSums[tile] += data[offset];
      greenSums[tile] += data[offset + 1];
      blueSums[tile] += data[offset + 2];
      tilePixels[tile] += 1;
    }

    for (let tile = 0; tile < tileCount; tile += 1) {
      const tilePixelCount = tilePixels[tile];
      if (tilePixelCount < 0.3 * tileWidth * tileHeight) continue;

      const column = tile % columns;
      const row = (tile - column) / columns;
      const tileLeft = Math.floor(minX + column * tileWidth);
      const tileTop = Math.floor(minY + row * tileHeight);
      const right = Math.ceil(minX + (column + 1) * tileWidth);
      const bottom = Math.ceil(minY + (row + 1) * tileHeight);
      if (Math.min(right - tileLeft, bottom - tileTop) < 5) continue;
      const x = Math.max(0, tileLeft - LOGO_SQUARE_PAD);
      const y = Math.max(0, tileTop - LOGO_SQUARE_PAD);
      squares.push({ x, y,
        width: Math.min(width, right + LOGO_SQUARE_PAD) - x,
        height: Math.min(height, bottom + LOGO_SQUARE_PAD) - y,
        familyIndex,
        rgb: [redSums[tile] / tilePixelCount / 255, greenSums[tile] / tilePixelCount / 255, blueSums[tile] / tilePixelCount / 255],
      });
    }
  }

  for (let familyIndex = 0; familyIndex < LOGO_FAMILY_RGBS.length; familyIndex += 1) {
    if (!squares.some((square) => square.familyIndex === familyIndex)) {
      throw new Error(`The logo bitmap has no squares for family ${familyIndex}`);
    }
  }

  return squares;
}

function createSeededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    let value = state = (state + 0x6d2b79f5) >>> 0;
    value = Math.imul(value ^ value >>> 15, 1 | value);
    value ^= value + Math.imul(value ^ value >>> 7, 61 | value);
    return ((value ^ value >>> 14) >>> 0) / 0x100000000;
  };
}

function centerX(square: LogoSquare): number {
  return square.x + square.width / 2;
}

function centerY(square: LogoSquare): number {
  return square.y + square.height / 2;
}

function rowOf(square: LogoSquare): number {
  return Math.round(centerY(square) / LOGO_SQUARE_PITCH);
}

function average<T>(items: readonly T[], select: (item: T) => number): number {
  return items.reduce((sum, item) => sum + select(item), 0) / items.length;
}

function assignmentsFor(squares: readonly LogoSquare[], cubes: readonly LatticeCube[]) {
  return LOGO_FAMILY_RGBS.flatMap((_, familyIndex) => {
    const familyCubes = cubes
      .filter((cube) => cube.familyIndex === familyIndex)
      .sort((left, right) => left.center.x - right.center.x);
    const familySquares = squares
      .filter((square) => square.familyIndex === familyIndex)
      .sort((left, right) => rowOf(left) - rowOf(right) || centerX(left) - centerX(right));
    const count = Math.min(familyCubes.length, familySquares.length);
    const groups = Array.from({ length: count }, (_, index) => [
      ...familySquares.slice(Math.floor(index * familySquares.length / count), Math.floor((index + 1) * familySquares.length / count)),
    ]).sort((left, right) => average(left, centerX) - average(right, centerX));

    return familyCubes.map((cube, index) => ({ cube, squares: groups[Math.floor(index * count / familyCubes.length)] ?? [] }));
  });
}

export function buildLogoPlan({
  squares,
  cubes = LATTICE_CUBES,
  width,
  height,
  direction,
}: {
  squares: readonly LogoSquare[];
  cubes?: readonly LatticeCube[];
  width: number;
  height: number;
  direction: LogoFlightDirection;
}): LogoPlan {
  if (!(width > 0) || !(height > 0)) throw new RangeError('Logo plan dimensions must be positive');

  const random = createSeededRandom(direction === 'outbound' ? 101 * 21 + 53 : 103 * 21 + 59);
  const assignments = assignmentsFor(squares, cubes);
  const flights = assignments.map(({ cube, squares: assignedSquares }) => {
    const delay = LOGO_HANDOFF + LOGO_DELAY_JITTER * random();
    const transformedY = direction === 'outbound'
      ? average(assignedSquares, centerY) / height
      : 1 - average(assignedSquares, centerY) / height;
    const clampedY = Math.min(1, Math.max(0, transformedY));
    const duration = LOGO_CUBE_FLIGHT + LOGO_SWEEP * clampedY + LOGO_LANDING_JITTER * random();
    return { cube, squares: assignedSquares, delay, landAt: delay + duration };
  });

  const rowLandingTimes = new Map<number, { top: number; bottom: number; landAt: number }>();
  for (const flight of flights) {
    for (const square of flight.squares) {
      const row = rowOf(square);
      const existing = rowLandingTimes.get(row);
      rowLandingTimes.set(row, {
        top: Math.min(square.y, existing?.top ?? Number.POSITIVE_INFINITY),
        bottom: Math.max(square.y + square.height, existing?.bottom ?? Number.NEGATIVE_INFINITY),
        landAt: Math.max(flight.landAt, existing?.landAt ?? Number.NEGATIVE_INFINITY),
      });
    }
  }

  const rows = [...rowLandingTimes].sort(([left], [right]) => left - right);
  const rowToLandingTime = new Map(rows.map(([row, data]) => [row, data.landAt]));
  let previousBottom = 0;
  const bands = rows.map(([, current], index) => {
    const next = rows[index + 1]?.[1];
    const bottom = next === undefined ? height : Math.max(previousBottom, (current.bottom + next.top) / 2);
    const band = { top: previousBottom, bottom, landAt: current.landAt };
    previousBottom = bottom;
    return band;
  });

  const completedFlights: LogoFlight[] = flights.map(({ cube, squares: assignedSquares, delay, landAt }) => ({
    cubeIndex: cube.cubeIndex,
    familyIndex: cube.familyIndex,
    cube,
    squares: assignedSquares,
    delay,
    landAt,
    settleFrom: Math.max(...assignedSquares.map((square) => rowToLandingTime.get(rowOf(square)) ?? 1)) + LOGO_ROW_FADE,
  }));

  return { width, height, direction, flights: completedFlights, bands };
}
