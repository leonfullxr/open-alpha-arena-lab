import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { Competition } from './api';

export function useCompetitionStream(competition: Competition | undefined): 'paused' | 'connected' | 'reconnecting' {
  const queryClient = useQueryClient();
  const [state, setState] = useState<'paused' | 'connected' | 'reconnecting'>('paused');

  useEffect(() => {
    if (!competition || competition.state !== 'RUNNING') { setState('paused'); return undefined; }
    const source = new EventSource(`/api/v1/public/competitions/${encodeURIComponent(competition.id)}/stream`);
    let fallback = 0;
    const refresh = (): void => {
      void queryClient.invalidateQueries({ queryKey: ['competition', competition.id] });
      void queryClient.invalidateQueries({ queryKey: ['competitions'] });
    };
    source.onopen = () => { setState('connected'); window.clearInterval(fallback); fallback = 0; };
    source.onmessage = refresh;
    source.onerror = () => {
      setState('reconnecting');
      if (!fallback) fallback = window.setInterval(refresh, 5_000);
    };
    return () => { source.close(); window.clearInterval(fallback); setState('paused'); };
  }, [competition?.id, competition?.state, queryClient]);

  return competition?.state === 'RUNNING' ? state : 'paused';
}
