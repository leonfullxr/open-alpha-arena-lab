import { ArrowDownRight, ArrowUpRight, Ban, CircleHelp, CircleMinus, CircleStop, Pause } from 'lucide-react';

const assetNames: Record<string, string> = {
  BTC: 'Bitcoin', ETH: 'Ethereum', SOL: 'Solana', BNB: 'BNB', DOGE: 'Dogecoin', XRP: 'XRP',
};

export function AssetIcon({ symbol, size = 18 }: { symbol: string; size?: number }): React.JSX.Element {
  const code = symbol.toUpperCase();
  const label = assetNames[code] ?? code;
  const common = { width: size, height: size, viewBox: '0 0 24 24', 'aria-hidden': true as const };
  let icon: React.JSX.Element;
  switch (code) {
    case 'BTC': icon = <svg {...common} className="asset-icon asset-icon--btc"><circle cx="12" cy="12" r="11" fill="currentColor" /><path d="M9 5.8v12.4M15 5.8v12.4M8.3 8h6a2.2 2.2 0 0 1 0 4.4h-5m0 0h5.4a2.2 2.2 0 0 1 0 4.4H8.3" fill="none" stroke="white" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" /></svg>; break;
    case 'ETH': icon = <svg {...common} className="asset-icon asset-icon--eth"><path d="M12 1.5 4.9 12 12 16.1 19.1 12 12 1.5Z" fill="currentColor" /><path d="M4.9 13.2 12 22.5l7.1-9.3L12 17.3l-7.1-4.1Z" fill="currentColor" opacity=".65" /></svg>; break;
    case 'SOL': icon = <svg {...common} className="asset-icon asset-icon--sol"><path d="M6 4h13l-3 3H3l3-3Zm-1 6h13l3 3H8l-3-3Zm3 7h13l-3 3H5l3-3Z" fill="currentColor" /></svg>; break;
    case 'BNB': icon = <svg {...common} className="asset-icon asset-icon--bnb"><g fill="currentColor"><path d="m12 1.5 3.2 3.2L12 7.9 8.8 4.7 12 1.5Zm6.3 6.3 3.2 3.2-3.2 3.2-3.2-3.2 3.2-3.2ZM5.7 7.8 8.9 11l-3.2 3.2L2.5 11l3.2-3.2ZM12 14.1l3.2 3.2-3.2 3.2-3.2-3.2 3.2-3.2Zm0-4.2 3.2 3.2L12 16.3 8.8 13.1l3.2-3.2Z" /></g></svg>; break;
    case 'DOGE': icon = <svg {...common} className="asset-icon asset-icon--doge"><circle cx="12" cy="12" r="11" fill="currentColor" /><path d="M8 7h4a5 5 0 0 1 0 10H8V7Zm0 5h8" fill="none" stroke="white" strokeWidth="1.7" strokeLinecap="round" /></svg>; break;
    case 'XRP': icon = <svg {...common} className="asset-icon asset-icon--xrp"><path d="M5.2 4h2.6l4.2 4.1L16.2 4h2.6l-5.5 5.4a1.9 1.9 0 0 1-2.6 0L5.2 4Zm13.6 16h-2.6L12 15.9 7.8 20H5.2l5.5-5.4a1.9 1.9 0 0 1 2.6 0l5.5 5.4Z" fill="currentColor" /></svg>; break;
    default: icon = <CircleHelp className="asset-icon asset-icon--unknown" size={size} aria-hidden="true" />;
  }
  return <span className="asset-icon-wrap" role="img" aria-label={`${label} (${code})`} title={`${label} (${code})`}>{icon}</span>;
}

function actionDetails(action?: string | null): { label: string; icon: typeof ArrowUpRight; tone: string } {
  const value = action?.trim().toUpperCase() ?? '';
  if (!value || value === 'NO_ACTION' || value === 'NONE') return { label: action || 'No action', icon: CircleMinus, tone: 'neutral' };
  if (value.includes('CANCEL') || value.includes('REJECT')) return { label: action!, icon: Ban, tone: 'negative' };
  if (value.includes('CLOSE') || value.includes('EXIT')) return { label: action!, icon: CircleStop, tone: 'neutral' };
  if (value.includes('HOLD') || value.includes('WAIT')) return { label: action!, icon: Pause, tone: 'neutral' };
  if (value.includes('BUY') || value.includes('LONG')) return { label: action!, icon: ArrowUpRight, tone: 'positive' };
  if (value.includes('SELL') || value.includes('SHORT')) return { label: action!, icon: ArrowDownRight, tone: 'negative' };
  return { label: action!, icon: CircleHelp, tone: 'neutral' };
}

export function ActionIcon({ action }: { action?: string | null }): React.JSX.Element {
  const { label, icon: Icon, tone } = actionDetails(action);
  return <span className={`action-icon action-icon--${tone}`} role="img" aria-label={label} title={label}><Icon aria-hidden="true" size={16} strokeWidth={2} /></span>;
}
