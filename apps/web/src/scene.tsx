import { useEffect } from 'react';
import { ART_HEIGHT, ART_WIDTH, FAMILY_COLORS, SLICE_COUNT, mixColor, profileAt, selectedSlice, slices, spanBounds, type Slice } from './geometry';

type Stage = 0 | 1 | 2 | 3 | 4;
type Vec = { x: number; y: number };
type Anchor = { stage: Stage; element: HTMLElement; canvas: HTMLCanvasElement; documentLeft: number; documentTop: number; width: number; height: number; drawnKey: string };
type Box = { left: number; top: number; width: number; height: number };
type Flight = { start: number; end: number; started: number; duration: number };

const forwardRatios = [0, 0.54, 0.62, 0.87, 0.4] as const;
const reverseHysteresis = [0, 0.13, 0.13, 0.13, 0.13] as const;
const chartTop = 120;
const chartBase = 700;
const chartOffsets = [0, .012, .024, .036, .048, .06] as const;

function path(ctx: CanvasRenderingContext2D, points: Vec[], close = false): void {
  if (!points.length) return;
  ctx.beginPath();
  ctx.moveTo(points[0]!.x, points[0]!.y);
  for (let index = 1; index < points.length; index += 1) ctx.lineTo(points[index]!.x, points[index]!.y);
  if (close) ctx.closePath();
}

function scaledBox(ctx: CanvasRenderingContext2D, box: Box, width = ART_WIDTH, height = ART_HEIGHT): void {
  ctx.translate(box.left, box.top);
  ctx.scale(box.width / width, box.height / height);
}

function slicePolygon(slice: Slice): Vec[] {
  return [...slice.points.map(({ x, y }) => ({ x, y })), { x: slice.points.at(-1)!.x, y: slice.baseline }, { x: slice.points[0]!.x, y: slice.baseline }];
}

function gridCellOrigin(id: number): Vec {
  const column = id % 20;
  const row = Math.floor(id / 20);
  return { x: 36 + column * 57.7, y: 60 + row * 67.2 };
}

function gridSlicePolygon(id: number): Vec[] {
  const slice = slices[id]!;
  const origin = gridCellOrigin(id);
  const upper = slice.points.map((point) => ({
    x: origin.x + point.x / ART_WIDTH * 34,
    y: origin.y + 3 + Math.max(0, Math.min(1, (point.y - 140) / 480)) * 29,
  }));
  return [...upper, { x: origin.x + 34, y: origin.y + 35 }, { x: origin.x, y: origin.y + 35 }];
}

function drawSlice(ctx: CanvasRenderingContext2D, points: Vec[], id: number, alpha = 1, selected = false, selectedFill = 0.13): void {
  const slice = slices[id]!;
  path(ctx, points, true);
  ctx.fillStyle = selected ? `rgba(200,150,29,${selectedFill * alpha})` : slice.color ? mixColor(slice.color, 0.14 * alpha) : `rgba(33,32,28,${(id === selectedSlice.id ? 0.06 : 0.018) * alpha})`;
  ctx.fill();
  ctx.strokeStyle = selected ? `rgba(200,150,29,${alpha})` : slice.color ? mixColor(slice.color, 0.7 * alpha) : `rgba(33,32,28,${(0.1 + slice.depth * 0.09) * alpha})`;
  ctx.lineWidth = selected ? 2 : 0.9;
  ctx.stroke();
}

function drawMountain(ctx: CanvasRenderingContext2D, box: Box): void {
  ctx.save();
  scaledBox(ctx, box);
  const order = slices.filter((slice) => slice.id !== selectedSlice.id);
  for (const slice of order) {
    const points = slicePolygon(slice);
    drawSlice(ctx, points, slice.id);
    if (slice.depth > 0.18) {
      const topRight = slice.points.at(-1)!;
      const backRight = { x: topRight.x + 11, y: topRight.y - 8 };
      const baseRight = { x: topRight.x, y: slice.baseline };
      path(ctx, [topRight, backRight, { x: backRight.x, y: slice.baseline - 8 }, baseRight], true);
      ctx.fillStyle = `rgba(33,32,28,${0.025 + slice.depth * 0.04})`;
      ctx.fill();
    }
    if (slice.color) {
      const band = slice.points.slice(34, 87);
      path(ctx, band);
      ctx.strokeStyle = mixColor(slice.color, 0.62);
      ctx.lineWidth = 3.2;
      ctx.stroke();
    }
  }
  const selected = selectedSlice;
  drawSlice(ctx, slicePolygon(selected), selected.id, 1, true, 0.035);
  path(ctx, selected.points.map(({ x, y }) => ({ x, y })));
  ctx.strokeStyle = '#c8961d';
  ctx.lineWidth = 2.6;
  ctx.stroke();
  ctx.restore();
}

function drawGrid(ctx: CanvasRenderingContext2D, box: Box, omitSelected = false): void {
  ctx.save();
  scaledBox(ctx, box, 1183, 835);
  for (let id = 0; id < SLICE_COUNT; id += 1) {
    if (omitSelected && id === selectedSlice.id) continue;
    drawSlice(ctx, gridSlicePolygon(id), id, id === selectedSlice.id ? 1 : 0.65, id === selectedSlice.id);
  }
  ctx.restore();
}

function chartSpanPolygon(index: number): Vec[] {
  const start = spanBounds[index]!;
  const end = spanBounds[index + 1]!;
  const left = 92 + start * 1028;
  const right = 92 + end * 1028;
  const contour = Array.from({ length: 26 }, (_, sample) => {
    const ratio = start + (end - start) * sample / 25;
    const point = profileAt(ratio);
    return { x: left + (right - left) * sample / 25, y: chartTop + (point.y - 140) / 480 * 500 };
  });
  return [{ x: left, y: chartBase }, ...contour, { x: right, y: chartBase }];
}

const chartSpans = Array.from({ length: 6 }, (_, index) => chartSpanPolygon(index));

function drawChart(ctx: CanvasRenderingContext2D, box: Box, fill = 1, separated = 0): void {
  ctx.save();
  scaledBox(ctx, box);
  for (let rule = 0; rule < 5; rule += 1) {
    const y = chartTop + rule * 135;
    ctx.beginPath(); ctx.moveTo(92, y); ctx.lineTo(1120, y);
    ctx.strokeStyle = 'rgba(33,32,28,0.09)'; ctx.lineWidth = 1; ctx.stroke();
  }
  ctx.beginPath(); ctx.moveTo(92, chartTop); ctx.lineTo(92, chartBase); ctx.lineTo(1120, chartBase);
  ctx.strokeStyle = 'rgba(33,32,28,0.7)'; ctx.lineWidth = 1.6; ctx.stroke();
  for (let span = 0; span < 6; span += 1) {
    const original = chartSpans[span]!;
    const offset = separated * chartOffsets[span]! * 1028;
    ctx.beginPath(); ctx.moveTo(original[0]!.x + offset, original[0]!.y);
    for (let point = 1; point < original.length; point += 1) ctx.lineTo(original[point]!.x + offset, original[point]!.y);
    ctx.closePath();
    ctx.fillStyle = mixColor(FAMILY_COLORS[span]!, 0.13 * fill); ctx.fill();
    ctx.beginPath(); ctx.moveTo(original[1]!.x + offset, original[1]!.y);
    for (let point = 2; point < original.length - 1; point += 1) ctx.lineTo(original[point]!.x + offset, original[point]!.y);
    ctx.strokeStyle = FAMILY_COLORS[span]!; ctx.lineWidth = 1.8; ctx.stroke();
    if (span > 0) {
      const x = 92 + spanBounds[span]! * 1028 + offset;
      ctx.setLineDash([4, 7]); ctx.beginPath(); ctx.moveTo(x, chartTop - 8); ctx.lineTo(x, chartBase + 4);
      ctx.strokeStyle = 'rgba(33,32,28,0.24)'; ctx.lineWidth = 1; ctx.stroke(); ctx.setLineDash([]);
    }
  }
  ctx.restore();
}

type Cube = { x: number; y: number; size: number; color: string; depth: number; family: number };

function cubeFor(family: number, within: number, box: Box): Cube {
  const angle = family * Math.PI / 3 - Math.PI / 2;
  const radius = 48 + Math.sqrt(within) * 61 + Math.sin(within * 8 + family) * 17;
  const lateral = Math.cos(within * 4.3 + family) * 56;
  const x = 590 + Math.cos(angle) * radius + Math.cos(angle + Math.PI / 2) * lateral;
  const y = 554 + Math.sin(angle) * radius * .74 + Math.sin(angle + Math.PI / 2) * lateral * .58;
  const side = Math.min(box.width, box.height);
  return {
    x: box.left + (box.width - side) / 2 + x / 1183 * side,
    y: box.top + (box.height - side) / 2 + y / 1183 * side,
    size: Math.min(box.width, box.height) * (8 + (within % 4) * 1.3) / 1183,
    color: FAMILY_COLORS[family]!,
    depth: y,
    family,
  };
}

function drawCube(ctx: CanvasRenderingContext2D, x: number, y: number, size: number, color: string, alpha = 1): void {
  const d = size * .58;
  const top = [{ x, y: y - d }, { x: x + size, y: y - d / 2 }, { x, y }, { x: x - size, y: y - d / 2 }];
  const left = [{ x: x - size, y: y - d / 2 }, { x, y }, { x, y: y + d }, { x: x - size, y: y + d / 2 }];
  const right = [{ x, y }, { x: x + size, y: y - d / 2 }, { x: x + size, y: y + d / 2 }, { x, y: y + d }];
  for (const [points, shade] of [[top, 1], [left, .68], [right, .82]] as const) {
    path(ctx, points, true);
    ctx.fillStyle = mixColor(color, alpha * shade); ctx.fill();
    ctx.strokeStyle = `rgba(249,249,248,${.48 * alpha})`; ctx.lineWidth = .8; ctx.stroke();
  }
}

function drawLattice(ctx: CanvasRenderingContext2D, box: Box, alpha = 1, includeCubes = true): void {
  const center = { x: box.left + box.width / 2, y: box.top + box.height * .48 };
  const points: Cube[] = Array.from({ length: 144 }, (_, index) => cubeFor(Math.floor(index / 24), index % 24, box));
  points.sort((a, b) => a.depth - b.depth);
  for (const point of points) {
    ctx.beginPath(); ctx.moveTo(center.x, center.y); ctx.lineTo(point.x, point.y);
    ctx.strokeStyle = `rgba(249,249,248,${.12 * alpha})`; ctx.lineWidth = .8; ctx.stroke();
    if (includeCubes) drawCube(ctx, point.x, point.y, point.size, point.color, .72 * alpha);
  }
}

type LogoStrip = { top: number; height: number };
let logoArtwork: HTMLCanvasElement | null = null;
let logoStrips: LogoStrip[] = [];

function getLogoArtwork(): HTMLCanvasElement {
  if (logoArtwork) return logoArtwork;
  const canvas = document.createElement('canvas');
  canvas.width = 512; canvas.height = 512;
  const context = canvas.getContext('2d');
  if (!context) return canvas;
  context.fillStyle = '#f9f9f8'; context.fillRect(0, 0, 512, 512);
  const weights = Array.from({ length: 36 }, (_, index) => .72 + ((index * 5) % 7) / 10);
  const total = weights.reduce((sum, weight) => sum + weight, 0);
  let y = 0;
  const colors = FAMILY_COLORS;
  for (let strip = 0; strip < 36; strip += 1) {
    const height = strip === 35 ? 512 - y : 512 * weights[strip]! / total;
    logoStrips.push({ top: y, height });
    const stripCenter = y + height / 2;
    const visualRow = stripCenter / 512 * 36;
    for (let column = 0; column < 24; column += 1) {
      const x = column + .5;
      const ring = Math.hypot((x - 7.7) / 1.1, (visualRow - 18) / 1.5);
      const letterO = ring > 5 && ring < 9;
      const stem = column >= 13 && column <= 15 && strip >= 3;
      const arm = column >= 15 && column <= 21 && strip >= 3 && strip <= 7;
      const diagonal = column >= 15 && column <= 22 && strip >= 8 && strip <= 19 && Math.abs((column - 18) - (strip - 13) * .48) < 1.3;
      const foot = column >= 15 && column <= 22 && strip >= 19 && strip <= 21;
      if (letterO || stem || arm || diagonal || foot) {
        context.fillStyle = colors[(column + Math.floor(strip / 4)) % colors.length]!;
        context.fillRect(column / 24 * 512, y, 512 / 24 + .8, height + .5);
      }
    }
    y += height;
  }
  logoArtwork = canvas;
  return canvas;
}

function logoBox(box: Box): Box {
  const side = Math.min(box.width, box.height);
  return { left: box.left + (box.width - side) / 2, top: box.top + (box.height - side) / 2, width: side, height: side };
}

function drawMark(ctx: CanvasRenderingContext2D, box: Box, alpha = 1): void {
  const bounds = logoBox(box);
  ctx.save(); ctx.globalAlpha = alpha;
  ctx.drawImage(getLogoArtwork(), bounds.left, bounds.top, bounds.width, bounds.height);
  ctx.restore();
}

function localBox(anchor: Anchor): Box {
  return { left: 0, top: 0, width: anchor.width, height: anchor.height };
}

function resamplePolygon(points: Vec[], count: number): Vec[] {
  const perimeter: Vec[] = [];
  for (let edge = 0; edge < points.length; edge += 1) {
    const start = points[edge]!;
    const end = points[(edge + 1) % points.length]!;
    const length = Math.hypot(end.x - start.x, end.y - start.y);
    perimeter.push({ x: length, y: edge });
  }
  const total = perimeter.reduce((sum, edge) => sum + edge.x, 0);
  return Array.from({ length: count }, (_, index) => {
    let distance = total * index / count;
    let edgeIndex = 0;
    while (edgeIndex < perimeter.length - 1 && distance > perimeter[edgeIndex]!.x) distance -= perimeter[edgeIndex++]!.x;
    const start = points[edgeIndex]!;
    const end = points[(edgeIndex + 1) % points.length]!;
    const ratio = distance / Math.max(.001, perimeter[edgeIndex]!.x);
    return { x: start.x + (end.x - start.x) * ratio, y: start.y + (end.y - start.y) * ratio };
  });
}

const morphCount = 64;
const gridSpanTemplates = Array.from({ length: 6 }, (_, span) => {
  const polygon = gridSlicePolygon(selectedSlice.id);
  const first = Math.round(spanBounds[span]! * 120); const last = Math.round(spanBounds[span + 1]! * 120);
  const top = polygon.slice(0, 121);
  return resamplePolygon([...top.slice(first, last + 1), { x: top[last]!.x, y: polygon[121]!.y }, { x: top[first]!.x, y: polygon[121]!.y }], morphCount);
});
const chartSpanTemplates = chartSpans.map((polygon) => resamplePolygon(polygon, morphCount));
const cubeSpanTemplates = Array.from({ length: 6 }, (_, family) => {
  const cube = cubeFor(family, 10, { left: 0, top: 0, width: 1183, height: 1183 });
  const size = cube.size * 3.2; const d = size * .58;
  const polygon = [{ x: cube.x, y: cube.y - d }, { x: cube.x + size, y: cube.y - d / 2 }, { x: cube.x + size, y: cube.y + d / 2 }, { x: cube.x, y: cube.y + d }, { x: cube.x - size, y: cube.y + d / 2 }, { x: cube.x - size, y: cube.y - d / 2 }];
  return resamplePolygon(polygon, morphCount);
});

function interpolateTemplate(ctx: CanvasRenderingContext2D, source: Vec[], sourceBox: Box, sourceWidth: number, sourceHeight: number, target: Vec[], targetBox: Box, targetWidth: number, targetHeight: number, progress: number, color: string, alpha = 1): void {
  ctx.beginPath();
  for (let index = 0; index < morphCount; index += 1) {
    const a = source[index]!; const b = target[index]!;
    const x1 = sourceBox.left + a.x / sourceWidth * sourceBox.width;
    const y1 = sourceBox.top + a.y / sourceHeight * sourceBox.height;
    const x2 = targetBox.left + b.x / targetWidth * targetBox.width;
    const y2 = targetBox.top + b.y / targetHeight * targetBox.height;
    const x = x1 + (x2 - x1) * progress; const y = y1 + (y2 - y1) * progress;
    if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.closePath();
  ctx.fillStyle = mixColor(color, alpha * .17); ctx.fill();
  ctx.strokeStyle = mixColor(color, alpha * .82); ctx.lineWidth = 1.35; ctx.stroke();
}

function transferMountainGrid(ctx: CanvasRenderingContext2D, source: Box, target: Box, progress: number): void {
  const amount = Math.min(1, Math.max(0, progress));
  for (let id = 0; id < SLICE_COUNT; id += 1) {
    const slice = slices[id]!;
    const gridOrigin = gridCellOrigin(id);
    const scaleX = source.width / ART_WIDTH; const scaleY = source.height / ART_HEIGHT;
    ctx.beginPath();
    for (let pointIndex = 0; pointIndex < 123; pointIndex += 1) {
      let x1: number; let y1: number; let x2: number; let y2: number;
      if (pointIndex < 121) {
        const point = slice.points[pointIndex]!;
        x1 = source.left + point.x * scaleX; y1 = source.top + point.y * scaleY;
        x2 = target.left + gridOrigin.x + point.x / ART_WIDTH * 34;
        y2 = target.top + gridOrigin.y + 3 + Math.max(0, Math.min(1, (point.y - 140) / 480)) * 29;
      } else {
        const right = pointIndex === 121; const point = slice.points[right ? 120 : 0]!;
        x1 = source.left + point.x * scaleX; y1 = source.top + slice.baseline * scaleY;
        x2 = target.left + gridOrigin.x + (right ? 34 : 0); y2 = target.top + gridOrigin.y + 35;
      }
      const x = x1 + (x2 - x1) * amount; const y = y1 + (y2 - y1) * amount;
      if (pointIndex === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.closePath();
    const selected = id === selectedSlice.id;
    ctx.fillStyle = selected ? 'rgba(200,150,29,.13)' : slice.color ? mixColor(slice.color, .12) : 'rgba(33,32,28,.018)'; ctx.fill();
    ctx.strokeStyle = selected ? '#c8961d' : slice.color ? mixColor(slice.color, .7) : 'rgba(33,32,28,.17)';
    ctx.lineWidth = selected ? 2 : .8; ctx.stroke();
  }
}

function transferGridChart(ctx: CanvasRenderingContext2D, source: Box, target: Box, progress: number): void {
  for (let index = 0; index < 6; index += 1) {
    interpolateTemplate(ctx, gridSpanTemplates[index]!, source, 1183, 835, chartSpanTemplates[index]!, target, ART_WIDTH, ART_HEIGHT, progress, FAMILY_COLORS[index]!);
  }
}

function transferChartLattice(ctx: CanvasRenderingContext2D, source: Box, target: Box, progress: number): void {
  for (let family = 0; family < 6; family += 1) {
    interpolateTemplate(ctx, chartSpanTemplates[family]!, source, ART_WIDTH, ART_HEIGHT, cubeSpanTemplates[family]!, target, 1183, 1183, progress, FAMILY_COLORS[family]!, .94);
  }
}

function transferLatticeMark(ctx: CanvasRenderingContext2D, source: Box, target: Box, progress: number): void {
  const artwork = getLogoArtwork();
  const bounds = logoBox(target);
  const clusters = Array.from({ length: 6 }, (_, family) => cubeFor(family, 12, source));
  for (let strip = 0; strip < 36; strip += 1) {
    const sourcePoint = clusters[strip % 6]!;
    const endY = bounds.top + logoStrips[strip]!.top / artwork.height * bounds.height;
    const endHeight = logoStrips[strip]!.height / artwork.height * bounds.height;
    const width = bounds.width * Math.max(.02, progress);
    const startLeft = sourcePoint.x - bounds.width * .08;
    const left = startLeft + (bounds.left - startLeft) * progress;
    const centerY = sourcePoint.y + (endY + endHeight / 2 - sourcePoint.y) * progress;
    const height = Math.max(1, endHeight * progress);
    const stripInfo = logoStrips[strip]!;
    ctx.drawImage(artwork, 0, stripInfo.top, artwork.width, stripInfo.height, left, centerY - height / 2, width, height);
  }
  if (progress >= .99) ctx.drawImage(artwork, bounds.left, bounds.top, bounds.width, bounds.height);
}

function transfer(ctx: CanvasRenderingContext2D, from: Stage, to: Stage, progress: number, boxes: Map<Stage, Box>): void {
  const source = boxes.get(from); const target = boxes.get(to);
  if (!source || !target) return;
  if (from === 0 && to === 1) transferMountainGrid(ctx, source, target, progress);
  else if (from === 1 && to === 2) transferGridChart(ctx, source, target, progress);
  else if (from === 2 && to === 3) transferChartLattice(ctx, source, target, progress);
  else if (from === 3 && to === 4) transferLatticeMark(ctx, source, target, progress);
}

function ease(t: number): number {
  const x1 = .22; const y1 = .61; const x2 = .24; const y2 = 1;
  let low = 0; let high = 1; let tValue = t;
  for (let iteration = 0; iteration < 12; iteration += 1) {
    const x = 3 * (1 - tValue) ** 2 * tValue * x1 + 3 * (1 - tValue) * tValue ** 2 * x2 + tValue ** 3;
    if (Math.abs(x - t) < .001) break;
    if (x < t) low = tValue; else high = tValue;
    tValue = (low + high) / 2;
  }
  return 3 * (1 - tValue) ** 2 * tValue * y1 + 3 * (1 - tValue) * tValue ** 2 * y2 + tValue ** 3;
}

function cubicBezierProgress(progress: number, x1: number, y1: number, x2: number, y2: number): number {
  let low = 0; let high = 1; let t = progress;
  for (let iteration = 0; iteration < 14; iteration += 1) {
    const inverse = 1 - t;
    const x = 3 * inverse * inverse * t * x1 + 3 * inverse * t * t * x2 + t * t * t;
    if (Math.abs(x - progress) < .0005) break;
    if (x < progress) low = t; else high = t;
    t = (low + high) / 2;
  }
  const inverse = 1 - t;
  return 3 * inverse * inverse * t * y1 + 3 * inverse * t * t * y2 + t * t * t;
}

function paintLocal(anchor: Anchor, ratio: number, options: { stagePosition: number; settledStage: Stage; split: number }): void {
  const canvas = anchor.canvas;
  const width = anchor.width; const height = anchor.height;
  const backingWidth = Math.max(1, Math.round(width * ratio));
  const backingHeight = Math.max(1, Math.round(height * ratio));
  const alpha = 1;
  const betweenGridAndChart = options.stagePosition > 1 && options.stagePosition < 2;
  const chartFill = betweenGridAndChart ? options.stagePosition - 1 : options.settledStage === 2 ? 1 : 0;
  const chartSeparation = options.settledStage === 2 ? options.split : options.settledStage > 2 ? 1 : 0;
  const selectedHidden = options.settledStage >= 2 || betweenGridAndChart;
  const key = [backingWidth, backingHeight, options.settledStage, anchor.stage === 2 ? `${chartFill.toFixed(3)}:${chartSeparation.toFixed(3)}` : '', anchor.stage === 1 && selectedHidden ? 'selected-hidden' : ''].join(':');
  if (canvas.width !== backingWidth) canvas.width = backingWidth;
  if (canvas.height !== backingHeight) canvas.height = backingHeight;
  if (anchor.drawnKey === key) return;
  anchor.drawnKey = key;
  const ctx = canvas.getContext('2d', { alpha: true });
  if (!ctx) { document.documentElement.classList.add('canvas-unavailable'); return; }
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0); ctx.clearRect(0, 0, width, height);
  const box = localBox(anchor);
  ctx.globalAlpha = alpha;
  if (anchor.stage === 0 && options.settledStage === 0) drawMountain(ctx, box);
  else if (anchor.stage === 1 && options.settledStage >= 1) drawGrid(ctx, box, selectedHidden);
  else if (anchor.stage === 2 && options.settledStage >= 1) drawChart(ctx, box, chartFill, chartSeparation);
  else if (anchor.stage === 3 && options.settledStage === 3) drawLattice(ctx, box, alpha);
  else if (anchor.stage === 4 && options.settledStage >= 4) drawMark(ctx, box, alpha);
}

function sampleFlight(flight: Flight | null, now: number, settled: number): number {
  if (!flight) return settled;
  const progress = Math.min(1, (now - flight.started) / flight.duration);
  return flight.start + (flight.end - flight.start) * ease(progress);
}

export function useSceneCoordinator(globalRef: React.RefObject<HTMLCanvasElement | null>, hostRef: React.RefObject<HTMLDivElement | null>): void {
  useEffect(() => {
    const globalCanvas = globalRef.current; const host = hostRef.current;
    if (!globalCanvas || !host) return undefined;
    const globalContext = globalCanvas.getContext('2d', { alpha: true });
    if (!globalContext) { document.documentElement.classList.add('canvas-unavailable'); return () => document.documentElement.classList.remove('canvas-unavailable'); }
    document.documentElement.classList.remove('canvas-unavailable');
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const anchors: Anchor[] = Array.from(host.querySelectorAll<HTMLElement>('[data-stage]')).map((element) => ({
      stage: Number(element.dataset.stage) as Stage,
      element,
      canvas: element.querySelector<HTMLCanvasElement>('.scene-local')!,
      documentLeft: 0, documentTop: 0, width: 0, height: 0, drawnKey: '',
    }));
    const byStage = new Map(anchors.map((anchor) => [anchor.stage, anchor]));
    let frame = 0; let viewportWidth = 0; let viewportHeight = 0; let dpr = 1;
    let thresholds = [0, 0, 0, 0] as number[];
    let settledStage: Stage = 0; let flight: Flight | null = null;
    let chartLandedAt = 0; let disposed = false;
    let lastScrollY = window.scrollY; let direction = 1;
    const artBoxes = new Map<Stage, Box>(anchors.map((anchor) => [anchor.stage, { left: 0, top: 0, width: 0, height: 0 }]));
    const boxes = (): Map<Stage, Box> => {
      for (const anchor of anchors) {
        const box = artBoxes.get(anchor.stage)!;
        box.left = anchor.documentLeft - window.scrollX; box.top = anchor.documentTop - window.scrollY;
        box.width = anchor.width; box.height = anchor.height;
      }
      return artBoxes;
    };
    const measure = (): void => {
      const scrollY = window.scrollY;
      for (const anchor of anchors) {
        const rect = anchor.element.getBoundingClientRect();
        anchor.documentLeft = rect.left + window.scrollX;
        anchor.documentTop = rect.top + scrollY;
        anchor.width = rect.width;
        anchor.height = rect.height;
        anchor.drawnKey = '';
      }
      viewportWidth = window.innerWidth; viewportHeight = window.innerHeight;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      globalCanvas.width = Math.max(1, Math.round(viewportWidth * dpr));
      globalCanvas.height = Math.max(1, Math.round(viewportHeight * dpr));
      globalCanvas.style.width = `${viewportWidth}px`; globalCanvas.style.height = `${viewportHeight}px`;
      globalContext.setTransform(dpr, 0, 0, dpr, 0, 0);
      for (let stage = 1; stage < 5; stage += 1) {
        const anchor = byStage.get(stage as Stage);
        if (!anchor) continue;
        thresholds[stage - 1] = anchor.documentTop - viewportHeight * forwardRatios[stage]!;
      }
      schedule();
    };
    const updateChartClass = (landed: boolean): void => {
      const chart = byStage.get(2)?.element.closest('.chart-wrap');
      chart?.classList.toggle('is-chart-landed', landed);
    };
    const resize = (): void => { measure(); flight = null; settledStage = 0; direction = 1; chartLandedAt = 0; updateChartClass(false); syncScroll(); };
    const paint = (now: number): void => {
      frame = 0;
      globalContext.clearRect(0, 0, viewportWidth, viewportHeight);
      let position = sampleFlight(flight, now, settledStage);
      if (flight && now - flight.started >= flight.duration) { position = flight.end; flight = null; }
      const transitionStage = Math.floor(position);
      const transitionProgress = position - transitionStage;
      const activePair = transitionProgress > .001 && transitionStage < 4;
      const splitElapsed = chartLandedAt ? Math.max(0, now - chartLandedAt - 600) : 0;
      const split = media.matches ? 1 : cubicBezierProgress(Math.min(1, splitElapsed / 450), .33, 1, .68, 1);
      const currentBoxes = boxes();
      for (const anchor of anchors) {
        const box = currentBoxes.get(anchor.stage)!;
        const onScreen = box.top < viewportHeight + 120 && box.top + box.height > -120;
        let localVisible = onScreen;
        if (activePair && transitionStage < 4) {
          const from = transitionStage as Stage; const to = (transitionStage + 1) as Stage;
          if ((from === 0 && to === 1) || (from === 2 && to === 3) || (from === 3 && to === 4)) localVisible = localVisible && anchor.stage !== from && anchor.stage !== to;
        }
        const visibility = localVisible ? 'visible' : 'hidden';
        if (anchor.canvas.style.visibility !== visibility) anchor.canvas.style.visibility = visibility;
        if (localVisible) paintLocal(anchor, dpr, { stagePosition: media.matches ? anchor.stage : position, settledStage: media.matches ? anchor.stage : settledStage, split });
      }
      if (activePair) {
        const from = transitionStage as Stage; const to = (transitionStage + 1) as Stage;
        transfer(globalContext, from, to, transitionProgress, currentBoxes);
      }
      if (!chartLandedAt && settledStage >= 2 && position >= 2) {
        chartLandedAt = now;
        updateChartClass(true);
      }
      if (!media.matches && (flight || (chartLandedAt > 0 && split < 1) || (chartLandedAt > 0 && now - chartLandedAt < 2300))) schedule();
    };
    function schedule(): void { if (!frame && !disposed) frame = requestAnimationFrame(paint); }
    const targetStageAt = (scrollY: number): Stage => {
      let target = settledStage;
      if (direction >= 0) {
        while (target < 4 && scrollY >= thresholds[target]!) target = (target + 1) as Stage;
      } else {
        while (target > 0 && scrollY < thresholds[target - 1]! - viewportHeight * reverseHysteresis[target]!) target = (target - 1) as Stage;
      }
      return target;
    };
    const syncScroll = (): void => {
      const scrollY = window.scrollY;
      if (scrollY !== lastScrollY) direction = Math.sign(scrollY - lastScrollY);
      lastScrollY = scrollY;
      const target = targetStageAt(scrollY);
      if (target !== settledStage) {
        const now = performance.now();
        const current = sampleFlight(flight, now, settledStage);
        const sourceStage = Math.max(0, Math.min(4, Math.floor(current))) as Stage;
        const sourceAnchor = byStage.get(sourceStage);
        const targetAnchor = byStage.get(target);
        const sourceVisible = sourceAnchor !== undefined && sourceAnchor.documentTop - scrollY < viewportHeight && sourceAnchor.documentTop + sourceAnchor.height - scrollY > 0;
        const targetVisible = targetAnchor !== undefined && targetAnchor.documentTop - scrollY < viewportHeight && targetAnchor.documentTop + targetAnchor.height - scrollY > 0;
        if (target < 2) { chartLandedAt = 0; updateChartClass(false); }
        settledStage = target;
        if (media.matches || (Math.abs(target - current) > 1 && targetVisible && !sourceVisible)) {
          flight = null;
          if (target >= 2) { if (!chartLandedAt) chartLandedAt = now; updateChartClass(true); }
        } else {
          flight = { start: current, end: target, started: now, duration: 760 * Math.max(.3, Math.abs(target - current)) };
        }
      }
      schedule();
    };
    const onMotionChange = (): void => {
      if (media.matches && flight) { settledStage = Math.round(flight.end) as Stage; flight = null; if (settledStage >= 2) { chartLandedAt = performance.now(); updateChartClass(true); } schedule(); }
    };
    const observer = new ResizeObserver(resize);
    observer.observe(host); for (const anchor of anchors) observer.observe(anchor.element);
    window.addEventListener('resize', resize, { passive: true });
    window.addEventListener('scroll', syncScroll, { passive: true });
    media.addEventListener('change', onMotionChange);
    measure(); syncScroll();
    let fontsReady = true;
    void document.fonts.ready.then(() => { if (disposed || !fontsReady) return; measure(); syncScroll(); schedule(); });
    return () => {
      disposed = true; fontsReady = false;
      document.documentElement.classList.remove('canvas-unavailable');
      window.removeEventListener('resize', resize); window.removeEventListener('scroll', syncScroll);
      media.removeEventListener('change', onMotionChange); observer.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, [globalRef, hostRef]);
}

export function svgFallback(stage: Stage): React.JSX.Element {
  if (stage === 0) return <svg className="scene-fallback" viewBox={`0 0 ${ART_WIDTH} ${ART_HEIGHT}`} aria-hidden="true">{slices.map((slice) => <path key={slice.id} d={[...slice.points.map((point, index) => `${index ? 'L' : 'M'}${point.x} ${point.y}`), `L${slice.points.at(-1)!.x} ${slice.baseline}L${slice.points[0]!.x} ${slice.baseline}Z`].join(' ')} fill={slice.id === selectedSlice.id ? 'rgba(200,150,29,.035)' : 'rgba(33,32,28,.018)'} stroke={slice.id === selectedSlice.id ? '#c8961d' : 'rgba(33,32,28,.2)'} strokeWidth={slice.id === selectedSlice.id ? 3 : 1} />)}</svg>;
  if (stage === 1) return <svg className="scene-fallback" viewBox="0 0 1183 835" aria-hidden="true">{slices.map((slice) => { const polygon = gridSlicePolygon(slice.id); return <polygon key={slice.id} points={polygon.map((point) => `${point.x},${point.y}`).join(' ')} fill={slice.id === selectedSlice.id ? 'rgba(200,150,29,.2)' : 'rgba(33,32,28,.025)'} stroke={slice.id === selectedSlice.id ? '#c8961d' : 'rgba(33,32,28,.22)'} strokeWidth={slice.id === selectedSlice.id ? 2 : 1} />; })}</svg>;
  if (stage === 2) return <svg className="scene-fallback" viewBox={`0 0 ${ART_WIDTH} ${ART_HEIGHT}`} aria-hidden="true">{Array.from({ length: 6 }, (_, index) => <polygon key={index} points={chartSpanPolygon(index).map((point) => `${point.x},${point.y}`).join(' ')} fill={mixColor(FAMILY_COLORS[index]!, .13)} stroke={FAMILY_COLORS[index]} />)}</svg>;
  if (stage === 3) return <svg className="scene-fallback" viewBox="0 0 1183 1183" aria-hidden="true">{Array.from({ length: 144 }, (_, index) => { const cube = cubeFor(Math.floor(index / 24), index % 24, { left: 0, top: 0, width: 1183, height: 1183 }); return <path key={index} d={`M${cube.x} ${cube.y - 8}l10 5v11l-10 5-10-5V${cube.y - 3}z`} fill={mixColor(cube.color, .72)} stroke="rgba(249,249,248,.48)" />; })}</svg>;
  return <svg className="scene-fallback" viewBox="0 0 24 24" aria-hidden="true">{Array.from({ length: 36 * 24 }, (_, cell) => {
    const strip = Math.floor(cell / 24); const column = cell % 24;
    const cx = column + .5; const cy = strip + .5;
    const ring = Math.hypot((cx - 7.7) / 1.1, (cy - 18) / 1.5);
    const ink = (ring > 5 && ring < 9) || (column >= 13 && column <= 15 && strip >= 4) || (column >= 15 && column <= 21 && strip >= 4 && strip <= 9) || (column >= 15 && column <= 22 && strip >= 10 && strip <= 28 && Math.abs((column - 18) - (strip - 19) * .48) < 1.3) || (column >= 15 && column <= 22 && strip >= 28 && strip <= 32);
    return ink ? <rect key={cell} x={column} y={strip / 36 * 24} width="1.02" height=".68" fill={FAMILY_COLORS[(column + Math.floor(strip / 4)) % 6]} /> : null;
  })}</svg>;
}
