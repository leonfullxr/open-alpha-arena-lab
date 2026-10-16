import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getCompetitionRules, type RulesArtifact } from './api';
import { decimal, decodeBase64Safely, money, sha256Hex } from './ui';

export function useRulesArtifact(competitionId: string) {
  return useQuery({
    queryKey: ['competition', competitionId, 'rules'],
    queryFn: () => getCompetitionRules(competitionId),
    enabled: Boolean(competitionId),
  });
}

export function RulesEvidence({ artifact }: { artifact: RulesArtifact }): React.JSX.Element {
  const decoded = useMemo(() => artifact.bytes_base64 ? decodeBase64Safely(artifact.bytes_base64) : { bytes: null, error: null }, [artifact.bytes_base64]);
  const [actualHash, setActualHash] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    setActualHash(null);
    if (decoded.bytes) {
      void sha256Hex(decoded.bytes).then((hash) => { if (current) setActualHash(hash); });
    }
    return () => { current = false; };
  }, [decoded.bytes]);
  const hashMatches = actualHash === artifact.sha256;

  function download(): void {
    if (!decoded.bytes || !hashMatches || artifact.bytes_withheld) return;
    const blob = new Blob([decoded.bytes], { type: 'application/octet-stream' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `competition-rules-${artifact.sha256}.json`;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
  }

  const policy = artifact.public;
  const facts: Array<[string, string]> = [
    ['Profile', policy.profile],
    ['Symbols', policy.symbols.join(', ')],
    ['Starting virtual capital', money(policy.initial_balance)],
    ['Round / response deadline', `${policy.round_seconds}s / ${policy.response_deadline_seconds}s`],
    ['Quote age / set skew limits', `${policy.quote_max_age_seconds}s / ${policy.quote_set_max_skew_seconds}s`],
    ['Maximum leverage', `${policy.leverage_max}×`],
    ['Commission / slippage', `${decimal(Number(policy.commission_rate) * 100, 3)}% / ${policy.slippage_bps} bps`],
    ['Daily loss / drawdown limits', `${money(policy.max_daily_loss)} / ${decimal(Number(policy.max_drawdown_fraction) * 100, 2)}%`],
    ['Maintenance margin / liquidation fee', `${decimal(Number(policy.maintenance_margin_rate) * 100, 2)}% / ${decimal(Number(policy.liquidation_fee_rate) * 100, 2)}%`],
    ['Funding method', `${policy.funding_mode} · ${policy.funding_rate_basis} · ${policy.funding_price_basis}`],
    ['Risk policy', policy.risk_policy_version],
    ['Evidence schemas', `snapshot ${policy.snapshot_schema_version} · proposal ${policy.proposal_schema_version} · public ${policy.public_evidence_schema_version} · ${policy.market_window_candles} candles`],
  ];
  if (policy.inference_budget_usd !== null) facts.push(['Inference budget', money(policy.inference_budget_usd)]);
  if (policy.fixture_source) facts.push(['Fixture source', policy.fixture_source]);

  return <section className="rules-evidence" aria-label="Public rules evidence">
    <div className="rules-evidence-heading"><strong>RULES SHA-256</strong><code>{artifact.sha256}</code></div>
    {actualHash !== null && <p className={hashMatches ? 'evidence-hash-ok' : 'query-error'} role={hashMatches ? 'status' : 'alert'}>{hashMatches ? 'Exact stored rules bytes verified.' : actualHash === 'unavailable' ? 'Rules hash verification is unavailable.' : 'Stored rules bytes do not match the reported SHA-256.'}</p>}
    <dl>{facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
    {artifact.withheld_fields && <p className="availability-note">The API omitted fields outside the safe public projection.</p>}
    {artifact.bytes_withheld ? <p className="availability-note">Exact rules bytes are withheld because the stored record contains fields the public contract does not recognize.</p>
      : decoded.error ? <p className="query-error" role="alert">Exact rules bytes could not be decoded: {decoded.error}</p>
        : decoded.bytes ? <button className="small-button" onClick={download} disabled={!hashMatches}>DOWNLOAD EXACT FROZEN RULES BYTES</button>
          : <p className="availability-note">The API did not return exact frozen rule bytes.</p>}
  </section>;
}
