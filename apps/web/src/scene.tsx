import { useEffect } from 'react';
import {
  ART_WIDTH, CHART_BASE, FAMILY_COLORS, FAMILY_RIM_COLORS, SOURCE_SIZE, chartContour,
  chartPointAtLinear, chartSpans, mixColor, selectedSlice, slices, sourceRenderOrderSlices,
  type Point, type Slice,
} from './geometry';
import {
  CHART_FLIGHTS, chartFamilyColumns, LATTICE_CUBES, LATTICE_DRAW_OPS, LATTICE_TETHERS,
  type LatticeCube,
} from './lattice-geometry';
import { paintBrandMark } from './branding';
import { svgFallback } from './scene-fallback';
import { createPanelRenderer, type PanelPose, type PanelRenderer } from './panel-webgl';
import {
  buildLogoPlan as createLogoPlan,
  LOGO_FAMILY_RGBS,
  segmentLogoSquares,
  type LogoPlan,
} from './logo-geometry';
export { svgFallback };

type Stage = 0 | 1 | 2 | 3 | 4;
type Box = { left: number; top: number; width: number; height: number };
type Vec = { x: number; y: number };
type Anchor = { stage: Stage; element: HTMLElement; canvas: HTMLCanvasElement; left: number; top: number; width: number; height: number };
type Leg = { from: Stage; to: Stage; target: Stage; started: number; duration: number; progressStart: number; progressEnd: number };

const DURATION = [1000, 1000, 900, 1800] as const;
const GRID_DURATION = 700;
const GRID_STAGGER = 300;
const OBSERVED_FALLBACK_FADE_MS = 600;
const GRID_SELECTION_SETTLE_MS = 900;
const GRID_FRAME = { width: 1183, height: 860 };
const SELECTED_TONE = '#fb8f52';
const GRID_COLUMNS = 20;

function clamp(value: number): number { return Math.max(0, Math.min(1, value)); }
function cubicOut(value: number): number { return 1 - Math.pow(1 - clamp(value), 3); }
function bezierOut(value: number): number {
  const x1 = .33; const y1 = 1; const x2 = .68; const y2 = 1;
  let lo = 0; let hi = 1; let t = value;
  for (let index = 0; index < 12; index += 1) {
    const inverse = 1 - t;
    const x = 3 * inverse * inverse * t * x1 + 3 * inverse * t * t * x2 + t * t * t;
    if (Math.abs(x - value) < .0005) break;
    if (x < value) lo = t; else hi = t;
    t = (lo + hi) / 2;
  }
  const inverse = 1 - t;
  return 3 * inverse * inverse * t * y1 + 3 * inverse * t * t * y2 + t * t * t;
}
function path(ctx: CanvasRenderingContext2D, points: readonly Vec[], close = false): void {
  const first = points[0];
  if (!first) return;
  ctx.beginPath(); ctx.moveTo(first.x, first.y);
  for (let index = 1; index < points.length; index += 1) {
    const point = points[index]!; ctx.lineTo(point.x, point.y);
  }
  if (close) ctx.closePath();
}
function blend(a: Vec, b: Vec, amount: number): Vec {
  return { x: a.x + (b.x - a.x) * amount, y: a.y + (b.y - a.y) * amount };
}
function sampleLine(from: readonly Vec[], to: readonly Vec[], amount: number): Vec[] {
  const count = Math.min(from.length, to.length);
  return Array.from({ length: count }, (_, index) => blend(from[index]!, to[index]!, amount));
}
function profilePolygon(slice: Slice): Vec[] {
  const first = slice.points[0]!; const last = slice.points.at(-1)!;
  return [...slice.points, { x: last.x, y: slice.baseline }, { x: first.x, y: slice.baseline }];
}
function gridPolygon(id: number): Vec[] {
  const slice = slices[id]!;
  const gridWidth = GRID_COLUMNS + (GRID_COLUMNS - 1) * .14;
  const cellWidth = GRID_FRAME.width / gridWidth;
  const cellHeight = GRID_FRAME.height / GRID_FRAME.width * cellWidth;
  const scale = cellWidth / GRID_FRAME.width;
  const cellLeft = (id % GRID_COLUMNS) * 1.14 * cellWidth;
  const cellTop = Math.floor(id / GRID_COLUMNS) * 2.1 * cellHeight;
  const offsetY = cellTop - 340 * scale;
  return [...slice.points.map((point) => ({ x: cellLeft + point.x * scale, y: offsetY + point.y * scale })),
    { x: cellLeft + slice.points.at(-1)!.x * scale, y: offsetY + slice.baseline * scale },
    { x: cellLeft + slice.points[0]!.x * scale, y: offsetY + slice.baseline * scale }];
}
function gridPanelPose(slice: Slice, box: Box, opacity = 1, plain = 0): PanelPose {
  const gridWidth = GRID_COLUMNS + (GRID_COLUMNS - 1) * .14;
  const cellWidth = GRID_FRAME.width / gridWidth;
  const cellHeight = GRID_FRAME.height / GRID_FRAME.width * cellWidth;
  const cellScale = cellWidth / GRID_FRAME.width;
  const scale = box.width / GRID_FRAME.width * cellScale;
  const cellLeft = (slice.id % GRID_COLUMNS) * 1.14 * cellWidth;
  const cellTop = Math.floor(slice.id / GRID_COLUMNS) * 2.1 * cellHeight;
  const anchorScale = scale / cellScale;
  return {
    profile: slice,
    x: box.left + cellLeft * anchorScale,
    y: box.top + (cellTop - 340 * cellScale) * anchorScale,
    scale,
    opacity,
    material: { isSignal: slice.isSelected, brightness: 0, revealEdge: SOURCE_SIZE + 10, plain },
  };
}
function gridCellBounds(id: number, box: Box): Box {
  const columns = GRID_COLUMNS + (GRID_COLUMNS - 1) * .14;
  const cellWidth = box.width / columns;
  const cellHeight = GRID_FRAME.height / GRID_FRAME.width * cellWidth;
  return {
    left: box.left + (id % GRID_COLUMNS) * 1.14 * cellWidth,
    top: box.top + Math.floor(id / GRID_COLUMNS) * 2.1 * cellHeight,
    width: cellWidth,
    height: cellHeight,
  };
}
function gridCellPanelPose(slice: Slice, cell: Box, opacity: number, brightness: number): PanelPose {
  const scale = cell.width / GRID_FRAME.width;
  return {
    profile: slice,
    x: cell.left,
    y: cell.top - 340 * scale,
    scale,
    opacity,
    material: { isSignal: slice.isSelected, brightness, revealEdge: SOURCE_SIZE + 10, plain: 0 },
  };
}
function mountainPanelPose(slice: Slice, box: Box, opacity = 1, plain = 0): PanelPose {
  const frame = screenFrame(box);
  return { profile: slice, x: frame.left, y: frame.top, scale: frame.width / ART_WIDTH, opacity,
    material: { isSignal: slice.isSelected, brightness: 0, revealEdge: SOURCE_SIZE, plain } };
}
function panelPoses(box: Box, kind: 'mountain' | 'grid', opacity = 1, plain = 0): PanelPose[] {
  return sourceRenderOrderSlices.map((slice) => kind === 'mountain'
    ? mountainPanelPose(slice, box, opacity, plain)
    : gridPanelPose(slice, box, opacity, plain));
}
function gridFlightPoses(source: Box, target: Box, progress: number, reverse = false): PanelPose[] {
  const sourceFrame = reverse ? source : screenFrame(source);
  const targetFrame = reverse ? screenFrame(target) : target;
  return sourceRenderOrderSlices.map((slice, arrayIndex) => {
    const delay = (reverse ? arrayIndex : sourceRenderOrderSlices.length - 1 - arrayIndex) / Math.max(1, sourceRenderOrderSlices.length - 1) * GRID_STAGGER;
    const amount = cubicOut(clamp((progress * (GRID_DURATION + GRID_STAGGER) - delay) / GRID_DURATION));
    const from = reverse ? gridPanelPose(slice, source) : mountainPanelPose(slice, sourceFrame, 1, 0);
    const to = reverse ? mountainPanelPose(slice, targetFrame, 1, 0) : gridPanelPose(slice, target);
    return {
      ...from,
      x: from.x + (to.x - from.x) * amount,
      y: from.y + (to.y - from.y) * amount,
      scale: from.scale + (to.scale - from.scale) * amount,
      opacity: from.opacity + (to.opacity - from.opacity) * amount,
      material: { ...from.material, plain: from.material.plain + (to.material.plain - from.material.plain) * amount },
    };
  });
}
const gridPolygons = slices.map((slice) => gridPolygon(slice.id));
const sourceRenderOrder = [...slices].reverse();
const chartContourPolygon: Vec[] = [...chartContour, { x: ART_WIDTH, y: CHART_BASE }, { x: 0, y: CHART_BASE }];

function screenFrame(box: Box): Box {
  const scale = Math.min(box.width / GRID_FRAME.width, box.height / GRID_FRAME.height);
  return { left: box.left + box.width / 2 - GRID_FRAME.width * scale / 2, top: box.top + box.height - SOURCE_SIZE * scale, width: GRID_FRAME.width * scale, height: SOURCE_SIZE * scale };
}
function projectPoints(points: readonly Vec[], box: Box, sourceWidth: number, sourceHeight: number): Vec[] {
  return points.map((point) => ({ x: box.left + point.x / sourceWidth * box.width, y: box.top + point.y / sourceHeight * box.height }));
}
function drawScreenPolygon(ctx: CanvasRenderingContext2D, points: readonly Vec[], fill: string, stroke: string, lineWidth: number): void {
  path(ctx, points, true); ctx.fillStyle = fill; ctx.fill(); ctx.strokeStyle = stroke; ctx.lineWidth = lineWidth; ctx.stroke();
}
let gritPattern: CanvasPattern | null | undefined;
function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    let value = state = (state + 0x6d2b79f5) >>> 0;
    value = Math.imul(value ^ value >>> 15, 1 | value);
    value ^= value + Math.imul(value ^ value >>> 7, 61 | value);
    return ((value ^ value >>> 14) >>> 0) / 0x100000000;
  };
}
function getGritPattern(ctx: CanvasRenderingContext2D): CanvasPattern | null {
  if (gritPattern !== undefined) return gritPattern;
  const tile = document.createElement('canvas'); tile.width = 360; tile.height = 360;
  const texture = tile.getContext('2d');
  if (!texture) { gritPattern = null; return null; }
  const random = seededRandom(101 * 21 + 11); const pixels = texture.createImageData(360, 360);
  for (let index = 0; index < 360 * 360; index += 1) {
    if (random() > .1) continue;
    const color = random() < .55 ? [33, 32, 28] : [130, 130, 124]; const offset = index * 4;
    pixels.data[offset] = color[0]!; pixels.data[offset + 1] = color[1]!; pixels.data[offset + 2] = color[2]!; pixels.data[offset + 3] = Math.floor(40 + 120 * random());
  }
  texture.putImageData(pixels, 0, 0);
  for (let index = 0; index < 30; index += 1) {
    texture.globalAlpha = .25 + .4 * random(); texture.fillStyle = random() < .6 ? '#21201c' : '#82827c';
    texture.beginPath(); texture.ellipse(random() * 360, random() * 360, (.5 + random()) * 2, (.4 + .8 * random()) * 2, random() * Math.PI, 0, 2 * Math.PI); texture.fill();
  }
  gritPattern = ctx.createPattern(tile, 'repeat'); return gritPattern;
}
function drawPolygon(ctx: CanvasRenderingContext2D, points: readonly Vec[], box: Box, sourceWidth: number, sourceHeight: number, fill: string, stroke: string, lineWidth: number): void {
  ctx.save(); ctx.translate(box.left, box.top); ctx.scale(box.width / sourceWidth, box.height / sourceHeight);
  path(ctx, points, true); ctx.fillStyle = fill; ctx.fill();
  ctx.strokeStyle = stroke; ctx.lineWidth = lineWidth; ctx.stroke(); ctx.restore();
}
function drawMountain(ctx: CanvasRenderingContext2D, box: Box, alpha = 1): void {
  const frame = screenFrame(box);
  const scale = frame.width / ART_WIDTH;
  ctx.save(); ctx.translate(frame.left, frame.top); ctx.scale(scale, scale);
  ctx.beginPath(); ctx.rect(-20, -SOURCE_SIZE, ART_WIDTH + 40, SOURCE_SIZE * 2); ctx.clip();
  for (const slice of sourceRenderOrder) {
    const polygon = profilePolygon(slice);
    const body = polygon.slice(0, slice.points.length + 1);
    const rim = [{ x: -10, y: slice.baseline }, ...slice.points, { x: SOURCE_SIZE + 10, y: slice.baseline }];
    path(ctx, body, true);
    if (slice.isSelected) {
      const fill = ctx.createLinearGradient(0, 0, 0, SOURCE_SIZE);
      fill.addColorStop(0, SELECTED_TONE); fill.addColorStop(1, '#f26a2e'); ctx.fillStyle = fill;
    } else ctx.fillStyle = slice.color;
    ctx.globalAlpha = alpha * slice.alpha; ctx.fill();
    if (scale >= .12) {
      const pattern = getGritPattern(ctx);
      if (pattern) {
        pattern.setTransform(new DOMMatrix().translate(-slice.gritOffset.x, -slice.gritOffset.y).scale(.5));
        path(ctx, body, true); ctx.fillStyle = pattern;
        ctx.globalAlpha = alpha * (slice.isSelected ? .02 : .035) * slice.alpha; ctx.fill();
      }
    }
    path(ctx, rim); ctx.strokeStyle = slice.isSelected ? '#f18443' : slice.soft ? '#e2e1de' : '#fdfdfc';
    ctx.lineWidth = .6; ctx.globalAlpha = alpha * (slice.isSelected ? .8 : .32) * slice.alpha; ctx.stroke();
  }
  ctx.restore();
}
function paintGridSlice(ctx: CanvasRenderingContext2D, id: number, box: Box, alpha: number, selected: boolean): void {
  const polygon = gridPolygons[id]!;
  const fill = selected ? mixColor(SELECTED_TONE, .13 * alpha) : `rgba(33,32,28,${.035 * alpha})`;
  const stroke = selected ? mixColor(SELECTED_TONE, alpha) : `rgba(33,32,28,${.22 * alpha})`;
  drawPolygon(ctx, polygon, box, GRID_FRAME.width, GRID_FRAME.height, fill, stroke, selected ? 1.6 : .65);
}
function drawGrid(ctx: CanvasRenderingContext2D, box: Box, alpha = 1, includeSelected = true): void {
  for (const slice of slices) {
    if (includeSelected || slice.id !== selectedSlice.id) paintGridSlice(ctx, slice.id, box, alpha, slice.id === selectedSlice.id);
  }
}
function drawChart(ctx: CanvasRenderingContext2D, box: Box, options: { fill: number; split: number; axes: boolean; phase?: number; formation?: number }): void {
  const split = clamp(options.split);
  const formation = clamp(options.formation ?? 1);
  const frame = screenFrame(box);
  ctx.save(); ctx.translate(frame.left, frame.top); ctx.scale(frame.width / ART_WIDTH, frame.width / ART_WIDTH);
  if (formation < 1) {
    path(ctx, chartContourPolygon, true);
    ctx.fillStyle = mixColor(SELECTED_TONE, .16);
    ctx.globalAlpha = .56 * options.fill * (1 - formation);
    ctx.fill();
  }
  for (let index = 0; index < 6; index += 1) {
    const offset = index * .012 * ART_WIDTH * split;
    ctx.save(); ctx.translate(offset, 0);
    const contour = chartSpans[index]!;
    const points = [{ x: contour[0]!.x, y: CHART_BASE }, ...contour, { x: contour.at(-1)!.x, y: CHART_BASE }];
    ctx.fillStyle = FAMILY_COLORS[index]!;
    if (options.phase === undefined) {
      path(ctx, points, true); ctx.globalAlpha = .56 * options.fill * formation; ctx.fill();
    } else {
      const columns = chartFamilyColumns[index]!.columnEdges;
      for (let column = 0; column < columns.length - 1; column += 1) {
        const left = columns[column]! * SOURCE_SIZE; const right = columns[column + 1]! * SOURCE_SIZE;
        const segment = [chartPointAtLinear(left / ART_WIDTH), ...chartContour.filter((point) => point.x > left && point.x < right), chartPointAtLinear(right / ART_WIDTH)];
        const opacity = 1 - clamp((options.phase - .02 * index - .1 * column / (columns.length - 1)) / .12);
        const segmentPolygon = [{ x: segment[0]!.x, y: CHART_BASE }, ...segment, { x: segment.at(-1)!.x, y: CHART_BASE }];
        path(ctx, segmentPolygon, true); ctx.globalAlpha = .56 * options.fill * formation * opacity; ctx.fill();
      }
    }
    ctx.globalAlpha = formation; path(ctx, points.slice(1, -1)); ctx.strokeStyle = FAMILY_RIM_COLORS[index]!; ctx.lineWidth = 1.75; ctx.stroke();
    ctx.restore();
  }
  ctx.restore();
}

function latticeBox(box: Box): Box {
  const side = Math.min(box.width, box.height);
  return { left: box.left + (box.width - side) / 2, top: box.top + (box.height - side) / 2, width: side, height: side };
}
function normalizedPoint(point: Point, box: Box): Vec { return { x: box.left + point.x * box.width, y: box.top + point.y * box.height }; }
function drawLattice(ctx: CanvasRenderingContext2D, box: Box, alpha = 1, includeCubes = true): void {
  const placed = latticeBox(box);
  ctx.save(); ctx.globalAlpha = alpha;
  for (const op of LATTICE_DRAW_OPS) {
    if (op.kind === 'tether') {
      const tether = LATTICE_TETHERS[op.tetherIndex]!;
      const from = normalizedPoint(tether.from, placed); const to = normalizedPoint(tether.to, placed);
      ctx.beginPath(); ctx.moveTo(from.x, from.y); ctx.lineTo(to.x, to.y);
      ctx.strokeStyle = `rgba(99,99,94,.3)`; ctx.lineWidth = 1; ctx.stroke();
    } else if (includeCubes) {
      const cube = LATTICE_CUBES[op.cubeIndex]!;
      drawLatticeCube(ctx, cube, placed);
    }
  }
  ctx.restore();
}
function drawLatticeCube(ctx: CanvasRenderingContext2D, cube: LatticeCube, box: Box): void {
  cube.faces.forEach((face) => {
    const points = face.map((point) => normalizedPoint(point, box)); path(ctx, points, true);
    ctx.fillStyle = latticeFaceColor(FAMILY_COLORS[cube.familyIndex]!); ctx.fill();
  });
  for (const edge of cube.edges) {
    const points = edge.map((point) => normalizedPoint(point, box)); path(ctx, points);
    ctx.strokeStyle = 'rgba(33,32,28,.3)'; ctx.lineWidth = 1; ctx.stroke();
  }
}
function drawLatticeCubeScaled(ctx: CanvasRenderingContext2D, cube: LatticeCube, box: Box, center: Vec, side: number, alpha: number): void {
  const placed = latticeBox(box); const origin = normalizedPoint(cube.center, placed);
  const scale = side / Math.max(1, placedCubeWidth(cube, box));
  const project = (point: Point): Vec => {
    const projected = normalizedPoint(point, placed);
    return { x: center.x + (projected.x - origin.x) * scale, y: center.y + (projected.y - origin.y) * scale };
  };
  ctx.save(); ctx.globalAlpha *= alpha;
  for (const face of cube.faces) {
    path(ctx, face.map(project), true); ctx.fillStyle = latticeFaceColor(FAMILY_COLORS[cube.familyIndex]!); ctx.fill();
  }
  for (const edge of cube.edges) {
    path(ctx, edge.map(project)); ctx.strokeStyle = 'rgba(33,32,28,.3)'; ctx.lineWidth = 1; ctx.stroke();
  }
  ctx.restore();
}
function latticeFaceColor(color: string): string {
  const value = Number.parseInt(color.slice(1), 16);
  const background = [249, 249, 248];
  const channels = [value >> 16, value >> 8 & 255, value & 255];
  return `rgb(${channels.map((channel, index) => Math.round(channel * .56 + background[index]! * .44)).join(',')})`;
}

let markBitmap: HTMLCanvasElement | undefined;
let logoSquares: ReturnType<typeof segmentLogoSquares> | undefined;
let outboundLogoPlan: LogoPlan | undefined;
let inboundLogoPlan: LogoPlan | undefined;
function getMarkBitmap(): HTMLCanvasElement {
  if (markBitmap) return markBitmap;
  const canvas = document.createElement('canvas'); canvas.width = 1024; canvas.height = 1024;
  const context = canvas.getContext('2d'); if (context) { context.scale(2, 2); paintBrandMark(context); }
  markBitmap = canvas; return canvas;
}
function getLogoSquares(): ReturnType<typeof segmentLogoSquares> {
  if (logoSquares) return logoSquares;
  const context = getMarkBitmap().getContext('2d');
  if (!context) return [];
  const bitmap = getMarkBitmap();
  logoSquares = segmentLogoSquares({ data: context.getImageData(0, 0, bitmap.width, bitmap.height).data, width: bitmap.width, height: bitmap.height });
  return logoSquares;
}
function buildLogoPlan(inbound = false): LogoPlan {
  const cached = inbound ? inboundLogoPlan : outboundLogoPlan;
  if (cached) return cached;
  const bitmap = getMarkBitmap();
  const plan = createLogoPlan({ squares: getLogoSquares(), width: bitmap.width, height: bitmap.height, direction: inbound ? 'inbound' : 'outbound' });
  if (inbound) inboundLogoPlan = plan; else outboundLogoPlan = plan;
  return plan;
}
function drawMark(ctx: CanvasRenderingContext2D, box: Box, alpha = 1): void {
  const side = Math.min(box.width, box.height);
  ctx.save(); ctx.globalAlpha = alpha; ctx.drawImage(getMarkBitmap(), box.left + (box.width - side) / 2, box.top + (box.height - side) / 2, side, side); ctx.restore();
}

function drawSelectedMorph(ctx: CanvasRenderingContext2D, source: Box, target: Box, progress: number, fromGrid: boolean): void {
  const targetProfile = chartContourPolygon;
  const sourcePoints = fromGrid ? gridPolygons[selectedSlice.id]! : targetProfile;
  const targetPoints = fromGrid ? targetProfile : gridPolygons[selectedSlice.id]!;
  const count = Math.min(sourcePoints.length, targetPoints.length);
  const alignedSource = sourcePoints.slice(0, count);
  const alignedTarget = targetPoints.slice(0, count);
  const amount = cubicOut(progress);
  const sourceFrame = fromGrid ? source : screenFrame(source);
  const targetFrame = fromGrid ? screenFrame(target) : target;
  const fromScreen = projectPoints(alignedSource, sourceFrame, fromGrid ? GRID_FRAME.width : GRID_FRAME.width, fromGrid ? GRID_FRAME.height : SOURCE_SIZE);
  const toScreen = projectPoints(alignedTarget, targetFrame, GRID_FRAME.width, fromGrid ? SOURCE_SIZE : GRID_FRAME.height);
  drawScreenPolygon(ctx, sampleLine(fromScreen, toScreen, amount), mixColor(SELECTED_TONE, .16), SELECTED_TONE, 1.75 * targetFrame.width / GRID_FRAME.width);
}

function legProgress(leg: Leg, now: number): number {
  const elapsed = clamp((now - leg.started) / Math.max(1, leg.duration));
  return leg.progressStart + (leg.progressEnd - leg.progressStart) * elapsed;
}
function chartFlightPoint(index: number, progress: number, chart: Box, lattice: Box): { point: Vec; side: number; cubeMorph: number; active: boolean } {
  const flight = CHART_FLIGHTS[index]!; const destination = LATTICE_CUBES[index]!;
  const chartFrame = screenFrame(chart);
  const start = {
    x: chartFrame.left + (flight.start.x * SOURCE_SIZE + .012 * flight.familyIndex * ART_WIDTH) / ART_WIDTH * chartFrame.width,
    y: chartFrame.top + flight.start.y * chartFrame.height,
  };
  const end = normalizedPoint(destination.center, latticeBox(lattice));
  const familyDelay = .02 * flight.familyIndex;
  const randomDelay = Math.max(0, flight.delay - flight.columnStart);
  const legProgress = clamp((progress - familyDelay - flight.columnStart - randomDelay) / .42);
  const delayed = legProgress;
  const pathProgress = 1 - Math.pow(1 - delayed, 2) * (1 + .5 * delayed);
  const startCenter = start;
  const point = blend(startCenter, end, pathProgress);
  const startSide = flight.side * SOURCE_SIZE / ART_WIDTH * chartFrame.width;
  const side = startSide * (1 - pathProgress) + placedCubeWidth(destination, lattice) * pathProgress;
  const cubeMorph = smoothstepRange(0, .5, legProgress);
  return { point, side, cubeMorph, active: progress - familyDelay > flight.columnStart };
}
function placedCubeWidth(cube: LatticeCube, box: Box): number { return cube.width * latticeBox(box).width; }
function cubicBezierEase(value: number, x1: number, y1: number, x2: number, y2: number): number {
  let low = 0; let high = 1; let t = clamp(value);
  for (let index = 0; index < 14; index += 1) {
    const inverse = 1 - t;
    const x = 3 * inverse * inverse * t * x1 + 3 * inverse * t * t * x2 + t * t * t;
    if (Math.abs(x - value) < .0004) break;
    if (x < value) low = t; else high = t;
    t = (low + high) / 2;
  }
  const inverse = 1 - t;
  return 3 * inverse * inverse * t * y1 + 3 * inverse * t * t * y2 + t * t * t;
}
function drawChartTethers(ctx: CanvasRenderingContext2D, placed: Box, progress: number, alpha: number): void {
  const t = clamp((progress - .4) / .6); const cubicInOut = t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  const center = normalizedPoint({ x: .5, y: .5 }, placed); const radius = placed.width * .52 * cubicInOut;
  if (radius <= 0 || alpha <= 0) return;
  ctx.save(); ctx.globalAlpha = alpha; ctx.beginPath(); ctx.arc(center.x, center.y, radius, 0, Math.PI * 2); ctx.clip();
  for (const tether of LATTICE_TETHERS) {
    const from = normalizedPoint(tether.from, placed); const to = normalizedPoint(tether.to, placed);
    ctx.beginPath(); ctx.moveTo(from.x, from.y); ctx.lineTo(to.x, to.y);
    ctx.strokeStyle = 'rgba(99,99,94,.3)'; ctx.lineWidth = 1; ctx.stroke();
  }
  ctx.restore();
}
function drawChartLattice(ctx: CanvasRenderingContext2D, chart: Box, lattice: Box, progress: number, split: number, dpr: number): void {
  drawChart(ctx, chart, { fill: 1, split, axes: true, phase: progress });
  const placed = latticeBox(lattice);
  const poses = LATTICE_CUBES.map((_, index) => chartFlightPoint(index, progress, chart, lattice));
  const frontMix = smoothstepRange(.76, .86, progress);
  drawChartTethers(ctx, placed, progress, 1 - frontMix);
  for (let index = 0; index < LATTICE_CUBES.length; index += 1) {
    const cube = LATTICE_CUBES[index]!; const pose = poses[index]!;
    if (!pose.active) continue;
    const size = pose.side + 1 / dpr; const squareAlpha = 1 - pose.cubeMorph; const spriteAlpha = Math.min(1, 2 * pose.cubeMorph);
    ctx.save(); ctx.globalAlpha = squareAlpha; ctx.fillStyle = latticeFaceColor(FAMILY_COLORS[cube.familyIndex]!);
    ctx.fillRect(pose.point.x - size / 2, pose.point.y - size / 2, size, size); ctx.restore();
    drawLatticeCubeScaled(ctx, cube, lattice, pose.point, pose.side, spriteAlpha);
  }
  drawChartTethers(ctx, placed, progress, frontMix);
  const latticeAlpha = cubicBezierEase(clamp((progress - .86) / .14), .65, 0, .35, 1);
  if (latticeAlpha > 0) drawLattice(ctx, lattice, latticeAlpha);
}

function smoothstepRange(start: number, end: number, value: number): number {
  const t = clamp((value - start) / (end - start)); return t * t * (3 - 2 * t);
}
function drawLogoTethers(ctx: CanvasRenderingContext2D, placed: Box, progress: number, alpha: number): void {
  const radius = placed.width * .52 * (1 - smoothstepRange(.03, .255, progress));
  if (radius <= 0 || alpha <= 0) return;
  const center = normalizedPoint({ x: .5, y: .5 }, placed);
  ctx.save(); ctx.globalAlpha = alpha; ctx.beginPath(); ctx.arc(center.x, center.y, radius, 0, Math.PI * 2); ctx.clip();
  for (const tether of LATTICE_TETHERS) {
    const from = normalizedPoint(tether.from, placed); const to = normalizedPoint(tether.to, placed);
    ctx.beginPath(); ctx.moveTo(from.x, from.y); ctx.lineTo(to.x, to.y);
    ctx.strokeStyle = 'rgba(99,99,94,.3)'; ctx.lineWidth = 1; ctx.stroke();
  }
  ctx.restore();
}
function drawLatticeMark(ctx: CanvasRenderingContext2D, lattice: Box, mark: Box, progress: number, inbound = false, seam = 1): void {
  const source = latticeBox(lattice); const targetSide = Math.min(mark.width, mark.height);
  const target = { left: mark.left + (mark.width - targetSide) / 2, top: mark.top + (mark.height - targetSide) / 2, width: targetSide, height: targetSide };
  const plan = buildLogoPlan(inbound); const bitmap = getMarkBitmap();
  const frontMix = 1 - smoothstepRange(.03, .09, progress);
  drawLogoTethers(ctx, source, progress, 1 - frontMix);
  const flights = [...plan.flights].sort((left, right) => left.cubeIndex - right.cubeIndex);
  for (const flight of flights) {
    const cubeCenter = normalizedPoint(flight.cube.center, source);
    const cubeSide = flight.cube.width * source.width;
    const local = clamp((progress - flight.delay) / Math.max(.001, flight.landAt - flight.delay));
    const motion = local * local * (3 - 2 * local);
    const cross = smoothstepRange(.15, .65, local);
    const settled = clamp((progress - flight.settleFrom) / .03);
    if (settled >= 1) continue;
    const first = flight.squares[0];
    if (first) {
      const quantized = Math.round(cross * 16) / 16;
      const rawFace = LOGO_FAMILY_RGBS[flight.familyIndex]!;
      const faceRgb = rawFace.map((value) => value * .56 + 249 * .44);
      for (let squareIndex = 0; squareIndex < flight.squares.length; squareIndex += 1) {
        const square = flight.squares[squareIndex]!;
        const destination = { x: target.left + (square.x + square.width / 2) / plan.width * target.width, y: target.top + (square.y + square.height / 2) / plan.height * target.height };
        const point = blend(cubeCenter, destination, motion);
        const tileWidth = target.width * square.width / plan.width;
        const tileHeight = target.height * square.height / plan.height;
        const width = cubeSide + (tileWidth - cubeSide) * motion;
        const height = cubeSide + (tileHeight - cubeSide) * motion;
        if (squareIndex === 0) drawLatticeCubeScaled(ctx, flight.cube, lattice, point, width, (1 - cross) * (1 - settled));
        if (cross <= 0) continue;
        const scaleX = width / square.width; const scaleY = height / square.height;
        const squareAlpha = (squareIndex === 0 ? Math.min(1, 2 * cross) : cross) * (1 - settled);
        const tileRgb = square.rgb.map((value) => value * 255);
        const color = `rgb(${faceRgb.map((value, index) => Math.round(value + (tileRgb[index]! - value) * quantized)).join(',')})`;
        const insetX = scaleX * smoothstepRange(.55, .9, local);
        const insetY = scaleY * smoothstepRange(.55, .9, local);
        ctx.save(); ctx.globalAlpha = squareAlpha; ctx.fillStyle = color;
        ctx.fillRect(point.x - width / 2 + insetX, point.y - height / 2 + insetY, Math.max(0, width - 2 * insetX) + seam, Math.max(0, height - 2 * insetY) + seam); ctx.restore();
        const patch = smoothstepRange(.55, .9, local);
        if (patch > 0) {
          const sourceX = Math.max(0, square.x - 2); const sourceY = Math.max(0, square.y - 2);
          const sourceRight = Math.min(plan.width, square.x + square.width + 2); const sourceBottom = Math.min(plan.height, square.y + square.height + 2);
          const expansionX = 2 * scaleX; const expansionY = 2 * scaleY;
          ctx.save(); ctx.globalAlpha = squareAlpha * patch;
          ctx.drawImage(bitmap, sourceX, sourceY, sourceRight - sourceX, sourceBottom - sourceY,
            point.x - width / 2 - expansionX, point.y - height / 2 - expansionY, width + expansionX * 2, height + expansionY * 2);
          ctx.restore();
        }
      }
    } else drawLatticeCubeScaled(ctx, flight.cube, lattice, cubeCenter, cubeSide, 1 - smoothstepRange(0, .03, progress));
  }
  drawLogoTethers(ctx, source, progress, frontMix);
  for (const band of plan.bands) {
    const alpha = clamp((progress - band.landAt) / .03);
    if (alpha <= 0) continue;
    ctx.save(); ctx.globalAlpha = alpha;
    ctx.drawImage(bitmap, 0, band.top, plan.width, band.bottom - band.top, target.left, target.top + band.top / plan.height * target.height, target.width, (band.bottom - band.top) / plan.height * target.height);
    ctx.restore();
  }
  const fullImage = clamp((progress - .98) / .02);
  if (fullImage > 0) drawMark(ctx, mark, fullImage);
}

function paintLocal(anchor: Anchor, ratio: number, split: number, settled: Stage, formation = 1, fallbackPhase?: number): void {
  const canvas = anchor.canvas;
  const width = anchor.width; const height = anchor.height;
  const bleed = anchor.stage === 2 ? 1.06 : 1;
  const targetWidth = Math.max(1, Math.round(width * ratio * bleed)); const targetHeight = Math.max(1, Math.round(height * ratio));
  if (canvas.width !== targetWidth) canvas.width = targetWidth;
  if (canvas.height !== targetHeight) canvas.height = targetHeight;
  canvas.style.left = ''; canvas.style.top = ''; canvas.style.right = ''; canvas.style.bottom = '';
  canvas.style.width = `${bleed * 100}%`; canvas.style.height = '100%';
  const context = canvas.getContext('2d', { alpha: true }); if (!context) return;
  context.setTransform(ratio, 0, 0, ratio, 0, 0); context.clearRect(0, 0, width * bleed, height);
  const local = { left: 0, top: 0, width, height };
  switch (anchor.stage) {
    case 0: drawMountain(context, local); break;
    case 1: drawGrid(context, local, settled >= 2 ? .09 : 1, settled < 2 || fallbackPhase !== undefined); break;
    case 2: drawChart(context, local, { fill: 1, split, axes: true, phase: fallbackPhase ?? (settled >= 3 ? 1 : undefined), formation }); break;
    case 3: drawLattice(context, local, fallbackPhase ?? (settled === 3 ? 1 : 0)); break;
    case 4: drawMark(context, local); break;
  }
}

export function useSceneCoordinator(globalRef: React.RefObject<HTMLCanvasElement | null>, hostRef: React.RefObject<HTMLDivElement | null>, panelRef?: React.RefObject<HTMLCanvasElement | null>): void {
  useEffect(() => {
    const globalCanvas = globalRef.current; const host = hostRef.current;
    if (!globalCanvas || !host) return undefined;
    const panelCanvas = panelRef?.current ?? null;
    let panelRenderer: PanelRenderer | null = panelCanvas ? createPanelRenderer(panelCanvas) : null;
    const stillCanvas = document.createElement('canvas');
    let stillRenderer: PanelRenderer | null = panelCanvas ? createPanelRenderer(stillCanvas) : null;
    const ctx = globalCanvas.getContext('2d', { alpha: true });
    if (!ctx) {
      const root = document.documentElement;
      const chartWrap = host.querySelector<HTMLElement>('.chart-wrap');
      const grid = host.querySelector<HTMLElement>('[data-stage="1"]');
      root.classList.add('canvas-unavailable');
      globalCanvas.dataset.renderer = 'svg-static';
      chartWrap?.classList.add('is-chart-landed');
      chartWrap?.style.setProperty('--chart-split', '1');
      chartWrap?.style.setProperty('--chart-unclick', '1');
      grid?.style.setProperty('--grid-marks-opacity', '0');
      host.querySelector('[data-stage="2"]')?.setAttribute('data-signal-mass-landed', 'true');
      return () => { root.classList.remove('canvas-unavailable'); panelRenderer?.dispose(); stillRenderer?.dispose(); };
    }
    document.documentElement.classList.remove('canvas-unavailable');
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const anchors: Anchor[] = Array.from(host.querySelectorAll<HTMLElement>('[data-stage]')).map((element) => ({
      stage: Number(element.dataset.stage) as Stage,
      element,
      canvas: element.querySelector<HTMLCanvasElement>('.scene-local')!,
      left: 0, top: 0, width: 0, height: 0,
    }));
    const byStage = new Map(anchors.map((anchor) => [anchor.stage, anchor]));
    const selectedGridLayers = new Map<Stage, { normal: HTMLCanvasElement; bright: HTMLCanvasElement }>();
    const gridAnchor = byStage.get(1);
    if (gridAnchor) {
      const normal = document.createElement('canvas'); const bright = document.createElement('canvas');
      normal.className = 'scene-local scene-grid-selected-normal'; bright.className = 'scene-local scene-grid-selected-bright';
      normal.setAttribute('aria-hidden', 'true'); bright.setAttribute('aria-hidden', 'true');
      normal.style.zIndex = '2'; bright.style.zIndex = '3'; normal.style.visibility = 'hidden'; bright.style.visibility = 'hidden';
      gridAnchor.element.append(normal, bright);
      selectedGridLayers.set(1, { normal, bright });
    }
    const stillKeys = new Map<HTMLCanvasElement, string>();
    const renderStill = (target: HTMLCanvasElement, cssWidth: number, cssHeight: number, poses: readonly PanelPose[], key: string, left: number, top: number): boolean => {
      if (!stillRenderer?.isAvailable()) return false;
      const cacheKey = `${key}:${cssWidth}:${cssHeight}:${dpr}`;
      target.style.left = `${left}px`; target.style.top = `${top}px`; target.style.right = 'auto'; target.style.bottom = 'auto';
      target.style.width = `${cssWidth}px`; target.style.height = `${cssHeight}px`;
      if (stillKeys.get(target) === cacheKey) return true;
      stillRenderer.resize(cssWidth, cssHeight, dpr);
      stillRenderer.draw(poses, true);
      target.width = Math.max(1, Math.round(cssWidth * dpr)); target.height = Math.max(1, Math.round(cssHeight * dpr));
      const context = target.getContext('2d', { alpha: true });
      if (!context) return false;
      context.setTransform(1, 0, 0, 1, 0, 0); context.clearRect(0, 0, target.width, target.height);
      context.drawImage(stillCanvas, 0, 0);
      stillKeys.set(target, cacheKey);
      return true;
    };
    const boxes = new Map<Stage, Box>();
    let width = 0; let height = 0; let dpr = 1; let raf = 0; let disposed = false;
    let settled: Stage = 0; let leg: Leg | null = null; let lastY = window.scrollY; let lastFlagY = window.scrollY; let lastScrollAt = performance.now(); let direction = 1; let chartLandedAt = 0; let gridLandedAt = 0;
    let thresholds = [0, 0, 0, 0]; let heroHold = 0;
    const chartWrap = byStage.get(2)?.element.closest<HTMLElement>('.chart-wrap');
    const chartAnchor = byStage.get(2)?.element;
    const updateRendererLabel = (): boolean => {
      const active = panelRenderer?.isAvailable() ?? false;
      globalCanvas.dataset.renderer = active ? 'webgl2+canvas2d' : 'canvas2d-fallback';
      return active;
    };
    const setLanded = (landed: boolean): void => {
      chartWrap?.classList.toggle('is-chart-landed', landed);
      chartWrap?.style.setProperty('--chart-split', String(landed ? 1 : 0));
      chartWrap?.style.setProperty('--chart-unclick', String(landed ? 1 : 0));
      chartAnchor?.setAttribute('data-signal-mass-landed', String(landed));
    };
    const measure = (): void => {
      const maxScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
      const heroArt = host.querySelector<HTMLElement>('.hero-art');
      heroHold = heroArt ? heroArt.getBoundingClientRect().height * .1 : 0;
      for (const anchor of anchors) {
        const rect = anchor.element.getBoundingClientRect();
        anchor.left = rect.left + window.scrollX; anchor.top = rect.top + window.scrollY; anchor.width = rect.width; anchor.height = rect.height;
        boxes.set(anchor.stage, { left: anchor.left - window.scrollX, top: anchor.top - window.scrollY, width: rect.width, height: rect.height });
      }
      width = window.innerWidth; height = window.innerHeight; dpr = Math.min(2, window.devicePixelRatio || 1);
      globalCanvas.width = Math.max(1, Math.round(width * dpr)); globalCanvas.height = Math.max(1, Math.round(height * dpr));
      globalCanvas.style.width = `${width}px`; globalCanvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      panelRenderer?.resize(width, height, dpr);
      for (let stage = 1; stage <= 4; stage += 1) {
        const anchor = byStage.get(stage as Stage); if (!anchor) continue;
        const ratio = stage === 1 ? .65 : .8;
        thresholds[stage - 1] = Math.min(maxScroll, Math.max(stage > 1 ? thresholds[stage - 2]! : heroHold, anchor.top - height * ratio));
      }
      schedule();
    };
    const absoluteStage = (scrollY: number): Stage => {
      let value = 0; while (value < 4 && scrollY >= thresholds[value]!) value += 1;
      return value as Stage;
    };
    const stageTarget = (fastJump: boolean): Stage => {
      if (window.scrollY < heroHold) return 0;
      if (fastJump) return absoluteStage(window.scrollY);
      if (Math.abs(window.scrollY - lastFlagY) < height * .1) return settled;
      let target = settled;
      if (direction >= 0) {
        while (target < 4) {
          const anchor = byStage.get((target + 1) as Stage)!;
          const requiresReadingLine = Boolean(leg) || target > settled;
          const trigger = requiresReadingLine ? Math.max(thresholds[target]!, anchor.top - height * .6) : thresholds[target]!;
          if (window.scrollY < trigger) break;
          target = (target + 1) as Stage;
        }
      } else while (target > 0 && window.scrollY < thresholds[target - 1]! - height * .1) target = (target - 1) as Stage;
      return target;
    };
    const snapTo = (target: Stage, now = performance.now()): void => {
      settled = target; leg = null;
      chartLandedAt = target >= 2 ? now - 1050 : 0;
      gridLandedAt = target >= 1 ? now - GRID_SELECTION_SETTLE_MS : 0;
      setLanded(media.matches || target >= 2);
    };
    const retarget = (target: Stage, now: number): void => {
      if (target === settled) return;
      const oldLeg = leg;
      if (media.matches) {
        settled = target; leg = null; setLanded(true); chartLandedAt = performance.now() - 1050; gridLandedAt = performance.now() - GRID_SELECTION_SETTLE_MS; return;
      }
      if (target < 2) { chartLandedAt = 0; setLanded(false); }
      if (oldLeg && (target === oldLeg.from || target === oldLeg.to)) {
        const progress = legProgress(oldLeg, now);
        const endpoint = target === oldLeg.from ? 0 : 1;
        const phaseDistance = Math.abs(oldLeg.progressEnd - oldLeg.progressStart);
        const phaseDuration = oldLeg.duration / Math.max(.001, phaseDistance);
        const remaining = Math.abs(endpoint - progress);
        leg = { ...oldLeg, target, started: now, duration: phaseDuration * Math.max(.04, remaining), progressStart: progress, progressEnd: endpoint };
        settled = target;
        return;
      }
      const from = target > settled + 1 ? (target - 1) as Stage : target < settled - 1 ? (target + 1) as Stage : settled;
      if (oldLeg || from !== settled) snapTo(from, now);
      settled = target;
      const duration = panelRenderer?.isAvailable()
        ? from === 0 || target === 0 ? GRID_DURATION + GRID_STAGGER : DURATION[Math.min(from, target)]!
        : OBSERVED_FALLBACK_FADE_MS;
      leg = { from, to: target, target, started: now, duration, progressStart: 0, progressEnd: 1 };
      if (from === 1 && target === 2) { chartLandedAt = 0; setLanded(false); }
    };
    const paint = (now: number): void => {
      raf = 0; ctx.clearRect(0, 0, width, height);
      const panelActive = updateRendererLabel();
      const stillActive = panelActive && (stillRenderer?.isAvailable() ?? false);
      if (panelCanvas) panelCanvas.style.visibility = panelActive ? 'visible' : 'hidden';
      const split = media.matches ? 1 : chartLandedAt ? bezierOut(clamp((now - chartLandedAt - 600) / 450)) : 0;
      const formation = media.matches ? 1 : chartLandedAt ? clamp((now - chartLandedAt) / 600) : 0;
      chartWrap?.style.setProperty('--chart-split', String(split));
      chartWrap?.style.setProperty('--chart-unclick', String(split));
      chartAnchor?.setAttribute('data-signal-mass-splitting', String(Boolean(chartLandedAt && split < 1)));
      if (chartLandedAt && split >= 1) setLanded(true);
      globalCanvas.dataset.activeStage = String(leg?.from ?? settled);
      globalCanvas.dataset.targetStage = String(settled);
      globalCanvas.dataset.transitionProgress = String(leg ? legProgress(leg, now) : 1);
      globalCanvas.dataset.direction = leg ? (leg.target > leg.from ? 'forward' : 'reverse') : 'idle';
      const localBoxes = new Map<Stage, Box>();
      const transitionProgress = leg ? legProgress(leg, now) : 0;
      for (const anchor of anchors) {
        const box = { left: anchor.left - window.scrollX, top: anchor.top - window.scrollY, width: anchor.width, height: anchor.height };
        localBoxes.set(anchor.stage, box);
        const visible = box.top < height + 80 && box.top + box.height > -80;
        const transitionOwnsCanvas = Boolean(panelActive && leg && (
          ((leg.from === 0 && leg.to === 1 || leg.from === 1 && leg.to === 0) && (anchor.stage === 0 || anchor.stage === 1))
          || anchor.stage === 2 && (leg.from === 1 || leg.to === 1 || leg.from === 2 || leg.to === 2)
          || anchor.stage === 3 && (leg.from === 2 || leg.to === 2 || leg.from === 3 || leg.to === 3)
          || anchor.stage === 4 && (leg.from === 3 || leg.to === 3)
        ));
        const ownsStage = media.matches
          || anchor.stage === 0 && settled === 0
          || anchor.stage === 1 && settled >= 1
          || anchor.stage === 2 && settled >= 2
          || anchor.stage === 3 && settled >= 3 && settled < 4
          || anchor.stage === 4 && settled === 4;
        const fallbackOwnsCanvas = Boolean(!panelActive && leg && (anchor.stage === leg.from || anchor.stage === leg.to));
        const canvasVisible = visible && (ownsStage || fallbackOwnsCanvas) && !transitionOwnsCanvas;
        let localOpacity = 1;
        let fallbackPhase: number | undefined;
        if (!panelActive && leg) {
          if (anchor.stage === leg.from) localOpacity = 1 - transitionProgress;
          else if (anchor.stage === leg.to) localOpacity = transitionProgress;
          if (leg.from === 2 && leg.to === 3 && anchor.stage === 2) fallbackPhase = transitionProgress;
          else if (leg.from === 3 && leg.to === 2 && anchor.stage === 2) fallbackPhase = 1 - transitionProgress;
          if (anchor.stage === 2 && (leg.from === 2 && leg.to === 3 || leg.from === 3 && leg.to === 2)) localOpacity = 1;
        }
        anchor.canvas.style.visibility = canvasVisible ? 'visible' : 'hidden';
        anchor.canvas.style.opacity = String(localOpacity);
        if (anchor.stage === 1) {
          const progress = leg ? legProgress(leg, now) : 0;
          const marks = leg?.from === 0 && leg.to === 1 ? 1 - progress : leg?.from === 1 && leg.to === 0 ? progress : settled === 0 ? 1 : 0;
          anchor.element.style.setProperty('--grid-marks-opacity', String(marks));
        }
        if (anchor.stage === 1) {
          const layers = selectedGridLayers.get(1);
          const inFlight = Boolean(leg && (leg.from === 0 && leg.to === 1 || leg.from === 1 && leg.to === 0 || leg.from === 1 && leg.to === 2 || leg.from === 2 && leg.to === 1));
          const fade = clamp((now - gridLandedAt) / GRID_SELECTION_SETTLE_MS);
          const selectedVisible = visible && stillActive && (settled < 2 || media.matches) && !inFlight;
          if (layers) {
            layers.normal.style.visibility = selectedVisible ? 'visible' : 'hidden';
            layers.bright.style.visibility = selectedVisible ? 'visible' : 'hidden';
            layers.normal.style.opacity = String(1 - fade);
            layers.bright.style.opacity = String(fade);
          }
          anchor.canvas.style.opacity = String(settled >= 2 || media.matches ? .09 : 1 - .91 * fade);
        }
        if (canvasVisible) {
          const localStage = !panelActive && anchor.stage === 3 && leg ? 3 : !panelActive && anchor.stage === 1 && leg?.from === 1 && leg.to === 2 ? 1 : settled;
          if (stillActive && anchor.stage === 0) {
            const inner = { left: 16, top: 16, width: anchor.width, height: anchor.height };
            const poses = panelPoses(inner, 'mountain');
            if (!renderStill(anchor.canvas, anchor.width + 32, anchor.height + 32, poses, 'mountain', -16, -16)) paintLocal(anchor, dpr, split, localStage, formation, fallbackPhase);
          } else if (stillActive && anchor.stage === 1) {
            const inner = { left: 16, top: 16, width: anchor.width, height: anchor.height };
            const base = sourceRenderOrderSlices.map((slice) => gridPanelPose(slice, inner, slice.isSelected ? 0 : 1));
            if (!renderStill(anchor.canvas, anchor.width + 32, anchor.height + 32, base, 'grid-base', -16, -16)) paintLocal(anchor, dpr, split, localStage, formation, fallbackPhase);
            const layers = selectedGridLayers.get(1);
            if (layers) {
              const cell = gridCellBounds(selectedSlice.id, inner);
              const cellLocal = { left: 16, top: 16, width: cell.width, height: cell.height };
              const normal = sourceRenderOrderSlices.map((slice) => gridCellPanelPose(slice, cellLocal, slice.isSelected ? 1 : 0, 0));
              const bright = sourceRenderOrderSlices.map((slice) => gridCellPanelPose(slice, cellLocal, slice.isSelected ? 1 : 0, 1));
              renderStill(layers.normal, cell.width + 32, cell.height + 32, normal, 'grid-selected-normal', cell.left - 16, cell.top - 16);
              renderStill(layers.bright, cell.width + 32, cell.height + 32, bright, 'grid-selected-bright', cell.left - 16, cell.top - 16);
            }
          } else {
            if (anchor.stage <= 1) stillKeys.delete(anchor.canvas);
            paintLocal(anchor, dpr, split, localStage, formation, fallbackPhase);
          }
        }
      }
      if (panelActive) {
        const mountainBox = localBoxes.get(0); const gridBox = localBoxes.get(1);
        if (leg && leg.from === 0 && leg.to === 1 && mountainBox && gridBox) {
          panelRenderer?.draw(gridFlightPoses(mountainBox, gridBox, legProgress(leg, now)), true);
        } else if (leg && leg.from === 1 && leg.to === 0 && mountainBox && gridBox) {
          panelRenderer?.draw(gridFlightPoses(gridBox, mountainBox, legProgress(leg, now), true), true);
        } else {
          const empty = gridBox ? panelPoses(gridBox, 'grid', 0) : sourceRenderOrderSlices.map((slice) => mountainPanelPose(slice, { left: 0, top: 0, width: 1, height: 1 }, 0));
          panelRenderer?.draw(empty, true);
        }
        if (!updateRendererLabel()) schedule();
      }
      if (leg) {
        const amount = legProgress(leg, now);
        const source = localBoxes.get(leg.from); const target = localBoxes.get(leg.to);
        if (source && target && panelActive) {
          if (leg.from === 1 && leg.to === 2) drawSelectedMorph(ctx, source, target, amount, true);
          else if (leg.from === 2 && leg.to === 1) drawSelectedMorph(ctx, source, target, amount, false);
          else if (leg.from === 2 && leg.to === 3) drawChartLattice(ctx, source, target, amount, split, dpr);
          else if (leg.from === 3 && leg.to === 2) drawChartLattice(ctx, target, source, 1 - amount, split, dpr);
          else if (leg.from === 3 && leg.to === 4) drawLatticeMark(ctx, source, target, amount, false, 1 / dpr);
          else if (leg.from === 4 && leg.to === 3) drawLatticeMark(ctx, target, source, 1 - amount, true, 1 / dpr);
        }
        if (amount === leg.progressEnd) {
          const completed = leg.target; const previous = leg.from; leg = null;
          if (completed === 2 && previous === 1 && settled === 2) {
            chartLandedAt = now; setLanded(false);
          }
          if (completed === 1 && previous === 0 && settled === 1) gridLandedAt = now;
          schedule();
        }
      }
      if (chartLandedAt && split < 1) schedule();
      if (gridLandedAt && settled === 1 && now - gridLandedAt < GRID_SELECTION_SETTLE_MS) schedule();
      if (leg) schedule();
    };
    function schedule(): void { if (!raf && !disposed) raf = requestAnimationFrame(paint); }
    const onScroll = (): void => {
      const now = performance.now(); const y = window.scrollY; const delta = y - lastY;
      if (delta !== 0) direction = Math.sign(delta);
      const elapsed = Math.max(1, now - lastScrollAt);
      const fastJump = Math.abs(delta) > height * 1.5 && Math.abs(delta) / elapsed * 1000 > height * 15;
      lastY = y; lastScrollAt = now;
      const target = stageTarget(fastJump);
      if (fastJump) {
        snapTo(target); lastFlagY = y;
      } else if (target !== settled) {
        retarget(target, now);
        lastFlagY = y;
      }
      schedule();
    };
    const onResize = (): void => {
      const previousWidth = width;
      measure();
      if (width !== previousWidth) {
        const target = absoluteStage(window.scrollY);
        if (target !== settled) snapTo(target);
        lastFlagY = window.scrollY;
      }
      lastY = window.scrollY; lastScrollAt = performance.now(); schedule();
    };
    const initializeAtCurrentScroll = (): void => {
      settled = absoluteStage(window.scrollY); leg = null;
      chartLandedAt = settled >= 2 ? performance.now() - 1050 : 0;
      gridLandedAt = settled >= 1 ? performance.now() - GRID_SELECTION_SETTLE_MS : 0;
      setLanded(media.matches || settled >= 2); lastY = window.scrollY; schedule();
    };
    const onMotionChange = (): void => {
      if (media.matches) {
        if (leg) { settled = leg.to; leg = null; }
        setLanded(true); chartLandedAt = performance.now() - 1050; gridLandedAt = performance.now() - GRID_SELECTION_SETTLE_MS;
      }
      schedule();
    };
    const observer = new ResizeObserver(onResize); observer.observe(host);
    for (const anchor of anchors) observer.observe(anchor.element);
    window.addEventListener('resize', onResize, { passive: true });
    window.addEventListener('scroll', onScroll, { passive: true }); media.addEventListener('change', onMotionChange);
    const onPanelContextChange = (): void => schedule();
    const onStillContextChange = (): void => { stillKeys.clear(); schedule(); };
    panelCanvas?.addEventListener('webglcontextlost', onPanelContextChange);
    panelCanvas?.addEventListener('webglcontextrestored', onPanelContextChange);
    stillCanvas.addEventListener('webglcontextlost', onStillContextChange);
    stillCanvas.addEventListener('webglcontextrestored', onStillContextChange);
    measure(); initializeAtCurrentScroll();
    void document.fonts.ready.then(() => { if (!disposed) measure(); });
    return () => {
      disposed = true; document.documentElement.classList.remove('canvas-unavailable');
      panelCanvas?.removeEventListener('webglcontextlost', onPanelContextChange);
      panelCanvas?.removeEventListener('webglcontextrestored', onPanelContextChange);
      stillCanvas.removeEventListener('webglcontextlost', onStillContextChange);
      stillCanvas.removeEventListener('webglcontextrestored', onStillContextChange);
      if (panelCanvas) panelCanvas.style.visibility = '';
      panelRenderer?.dispose(); panelRenderer = null; stillRenderer?.dispose(); stillRenderer = null;
      for (const layer of selectedGridLayers.values()) { layer.normal.remove(); layer.bright.remove(); }
      window.removeEventListener('resize', onResize); window.removeEventListener('scroll', onScroll);
      media.removeEventListener('change', onMotionChange); observer.disconnect(); if (raf) cancelAnimationFrame(raf);
    };
  }, [globalRef, hostRef, panelRef]);
}
