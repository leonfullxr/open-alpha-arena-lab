import { QueryClient } from '@tanstack/react-query';
import { canAutomaticallyRetry, retryPollInterval } from './api';

export function createSimulationQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: 0,
        retryOnMount: false,
        refetchInterval: (query) => retryPollInterval(query.state.error),
        refetchIntervalInBackground: true,
        refetchOnWindowFocus: (query) => canAutomaticallyRetry(query.state.error, query.state.errorUpdatedAt),
        refetchOnReconnect: (query) => canAutomaticallyRetry(query.state.error, query.state.errorUpdatedAt),
        staleTime: 2_000,
      },
      mutations: { retry: 0 },
    },
  });
}
