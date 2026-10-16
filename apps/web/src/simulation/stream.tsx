import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { Competition } from './api';

const CompetitionStreamContext = createContext<'paused' | 'connected' | 'reconnecting'>('paused');

export function CompetitionStreamProvider({ state, children }: { state: 'paused' | 'connected' | 'reconnecting'; children: ReactNode }): React.JSX.Element {
  return <CompetitionStreamContext.Provider value={state}>{children}</CompetitionStreamContext.Provider>;
}

export function useCompetitionStreamState(): 'paused' | 'connected' | 'reconnecting' {
  return useContext(CompetitionStreamContext);
}

export function useCompetitionStream(competition: Competition | undefined): 'paused' | 'connected' | 'reconnecting' {
  const queryClient = useQueryClient();
  const [state, setState] = useState<'paused' | 'connected' | 'reconnecting'>('paused');

  useEffect(() => {
    if (!competition) { setState('paused'); return undefined; }
    const refresh = (): void => {
      void queryClient.invalidateQueries({ queryKey: ['competition', competition.id] });
      void queryClient.invalidateQueries({ queryKey: ['competitions'] });
    };
    if (competition.state === 'PAUSED') {
      setState('paused');
      const refreshWhenVisible = (): void => {
        if (document.visibilityState === 'visible') refresh();
      };
      const refreshTimer = window.setInterval(refreshWhenVisible, 5_000);
      return () => window.clearInterval(refreshTimer);
    }
    if (competition.state !== 'RUNNING') { setState('paused'); return undefined; }
    const source = new EventSource(`/api/v1/public/competitions/${encodeURIComponent(competition.id)}/stream`);
    let fallback = 0;
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
