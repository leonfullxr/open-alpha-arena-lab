import type { JSX } from 'react';
import {
  ART_HEIGHT,
  ART_WIDTH,
  CHART_BASE,
  FAMILY_COLORS,
  FAMILY_RIM_COLORS,
  GRID_COLUMNS,
  GRID_GAP_X,
  GRID_GAP_Y,
  SOURCE_SIZE,
  chartSpans,
  selectedSlice,
  slices,
  sourceRenderOrderSlices,
  type Point,
  type Slice,
} from './geometry';
import { LATTICE_CUBES, LATTICE_DRAW_OPS, LATTICE_TETHERS } from './lattice-geometry';
import { BrandMark } from './branding';

type Stage = 0 | 1 | 2 | 3 | 4;

const ART_VIEW_BOX = `0 0 ${ART_WIDTH} ${ART_HEIGHT}`;
const SOURCE_Y_OFFSET = -340;
const PAGE_COLOR = '#f9f9f8';
const SELECTED_GOLD = '#c8961d';

function pointList(points: readonly Point[]): string {
  return points.map(({ x, y }) => `${x},${y}`).join(' ');
}

function mountainBody(slice: Slice): Point[] {
  const first = slice.points[0]!;
  const last = slice.points.at(-1)!;
  return [...slice.points, { x: last.x, y: slice.baseline }, { x: first.x, y: slice.baseline }];
}

function MountainFallback(): JSX.Element {
  return <svg className="scene-fallback" viewBox={ART_VIEW_BOX} aria-hidden="true" focusable="false">
    <defs>
      <linearGradient id="fallback-selected-profile" x1="0" y1="0" x2="0" y2={SOURCE_SIZE} gradientUnits="userSpaceOnUse">
        <stop offset="0" stopColor="#fb8f52" />
        <stop offset="1" stopColor="#f26a2e" />
      </linearGradient>
    </defs>
    <g transform={`translate(0 ${SOURCE_Y_OFFSET})`}>
      {sourceRenderOrderSlices.map((slice) => <g key={slice.id}>
        <polygon
          points={pointList(mountainBody(slice))}
          fill={slice.isSelected ? 'url(#fallback-selected-profile)' : slice.color}
          fillOpacity={slice.alpha}
        />
        <polyline
          points={pointList(slice.points)}
          fill="none"
          stroke={slice.isSelected ? '#f18443' : slice.soft ? '#e2e1de' : '#fdfdfc'}
          strokeWidth="0.6"
          strokeOpacity={slice.alpha * (slice.isSelected ? 0.8 : 0.32)}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      </g>)}
    </g>
  </svg>;
}

function gridCellPoints(slice: Slice): Point[] {
  const totalWidth = GRID_COLUMNS + (GRID_COLUMNS - 1) * GRID_GAP_X;
  const cellWidth = ART_WIDTH / totalWidth;
  const cellHeight = ART_HEIGHT / ART_WIDTH * cellWidth;
  const scale = cellWidth / ART_WIDTH;
  const left = slice.id % GRID_COLUMNS * (1 + GRID_GAP_X) * cellWidth;
  const top = Math.floor(slice.id / GRID_COLUMNS) * (1 + GRID_GAP_Y) * cellHeight - 340 * scale;
  const points = slice.points.map(({ x, y }) => ({ x: left + x * scale, y: top + y * scale }));
  const last = points.at(-1)!;
  const first = points[0]!;
  return [...points, { x: last.x, y: top + slice.baseline * scale }, { x: first.x, y: top + slice.baseline * scale }];
}

function GridFallback(): JSX.Element {
  return <svg className="scene-fallback" viewBox={ART_VIEW_BOX} aria-hidden="true" focusable="false">
    {slices.map((slice) => {
      const selected = slice.id === selectedSlice.id;
      return <polygon
        key={slice.id}
        points={pointList(gridCellPoints(slice))}
        fill={selected ? SELECTED_GOLD : '#21201c'}
        fillOpacity={selected ? 0.82 : 0.09}
        stroke={selected ? SELECTED_GOLD : 'rgba(33,32,28,0.22)'}
        strokeWidth={selected ? 1.6 : 0.65}
        strokeLinejoin="round"
      />;
    })}
  </svg>;
}

function opaquePastel(color: string): string {
  const value = Number.parseInt(color.slice(1), 16);
  const background = Number.parseInt(PAGE_COLOR.slice(1), 16);
  const channels = [16, 8, 0].map((shift) => {
    const source = value >> shift & 255;
    const page = background >> shift & 255;
    return Math.round(source * 0.56 + page * 0.44);
  });
  return `rgb(${channels[0]},${channels[1]},${channels[2]})`;
}

function chartSpanPoints(index: number): Point[] {
  const span = chartSpans[index]!;
  const offset = index * 0.012 * ART_WIDTH;
  return [{ x: span[0]!.x + offset, y: CHART_BASE },
    ...span.map(({ x, y }) => ({ x: x + offset, y })),
    { x: span.at(-1)!.x + offset, y: CHART_BASE }];
}

function ChartFallback(): JSX.Element {
  return <svg className="scene-fallback" viewBox={ART_VIEW_BOX} style={{ overflow: 'visible', clipPath: 'inset(0 -10% 0 0)' }} aria-hidden="true" focusable="false">
    <g transform={`translate(0 ${SOURCE_Y_OFFSET})`}>
      {chartSpans.map((_, index) => <g key={`span-${index}`}>
        <polygon points={pointList(chartSpanPoints(index))} fill={opaquePastel(FAMILY_COLORS[index]!)} />
      </g>)}
      {chartSpans.map((span, index) => <polyline key={`rim-${index}`} points={pointList(span.map(({ x, y }) => ({ x: x + index * 0.012 * ART_WIDTH, y })))} fill="none" stroke={FAMILY_RIM_COLORS[index]!} strokeWidth="1.75" strokeLinejoin="round" strokeLinecap="round" />)}
    </g>
  </svg>;
}

function latticeFaceColor(color: string): string {
  return opaquePastel(color);
}

function LatticeFallback(): JSX.Element {
  return <svg className="scene-fallback" viewBox="0 0 1 1" aria-hidden="true" focusable="false">
    {LATTICE_DRAW_OPS.map((operation, index) => operation.kind === 'tether'
      ? (() => {
        const tether = LATTICE_TETHERS[operation.tetherIndex]!;
        return <line key={`draw-${index}`} x1={tether.from.x} y1={tether.from.y} x2={tether.to.x} y2={tether.to.y} stroke="#63635e" strokeOpacity="0.3" strokeWidth="1" vectorEffect="non-scaling-stroke" />;
      })()
      : (() => {
        const cube = LATTICE_CUBES[operation.cubeIndex]!;
        return <g key={`draw-${index}`} fill={latticeFaceColor(FAMILY_COLORS[cube.familyIndex]!)}>
          <path d={cube.faces.map((face) => `M${face.map(({ x, y }) => `${x},${y}`).join('L')}Z`).join('')} />
          {cube.edges.map((edge, edgeIndex) => <polyline key={`edge-${edgeIndex}`} points={pointList(edge)} fill="none" stroke="#21201c" strokeWidth="1" vectorEffect="non-scaling-stroke" />)}
        </g>;
      })()
    )}
  </svg>;
}

export function svgFallback(stage: Stage): JSX.Element {
  if (stage === 0) return <MountainFallback />;
  if (stage === 1) return <GridFallback />;
  if (stage === 2) return <ChartFallback />;
  if (stage === 3) return <LatticeFallback />;
  return <BrandMark className="scene-fallback" />;
}
