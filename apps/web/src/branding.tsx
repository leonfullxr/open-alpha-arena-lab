export const BRAND_MARK_VIEW_BOX = '0 0 120 120';
export const BRAND_BRACKET_LEFT_PATH = 'M38 18 H18 V102 H38';
export const BRAND_BRACKET_RIGHT_PATH = 'M82 18 H102 V102 H82';
export const BRAND_ALPHA_PATH = 'M87 38 C81 64 73 86 55 86 C41 86 34 76 34 64 C34 52 41 42 55 42 C71 42 77 70 89 88';
export const BRAND_BRACKET_COLOR = '#0B0B0C';
export const BRAND_ALPHA_COLOR = '#00A15E';

/** Paint the supplied mark paths at their source viewBox size on the canvas. */
export function paintBrandMark(context: CanvasRenderingContext2D): void {
  const scale = 512 / 120;
  context.save();
  context.scale(scale, scale);
  context.lineCap = 'square';
  context.lineWidth = 8;
  context.strokeStyle = BRAND_BRACKET_COLOR;
  context.stroke(new Path2D(BRAND_BRACKET_LEFT_PATH));
  context.stroke(new Path2D(BRAND_BRACKET_RIGHT_PATH));
  context.lineWidth = 9;
  context.lineJoin = 'round';
  context.strokeStyle = BRAND_ALPHA_COLOR;
  context.stroke(new Path2D(BRAND_ALPHA_PATH));
  context.restore();
}

export function BrandMark({ className }: { className: string }): React.JSX.Element {
  return <svg className={className} viewBox={BRAND_MARK_VIEW_BOX} aria-hidden="true" focusable="false">
    <path d={BRAND_BRACKET_LEFT_PATH} fill="none" stroke={BRAND_BRACKET_COLOR} strokeWidth="8" strokeLinecap="square" />
    <path d={BRAND_BRACKET_RIGHT_PATH} fill="none" stroke={BRAND_BRACKET_COLOR} strokeWidth="8" strokeLinecap="square" />
    <path d={BRAND_ALPHA_PATH} fill="none" stroke={BRAND_ALPHA_COLOR} strokeWidth="9" strokeLinecap="square" strokeLinejoin="round" />
  </svg>;
}
