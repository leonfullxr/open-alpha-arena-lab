import React, { Suspense } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import '../tokens.css';
import '../simulation.css';
import { SimulationShell } from './shell';

const DirectoryPage = React.lazy(() => import('./directory'));
const CompetitionPage = React.lazy(() => import('./competition'));
const LeaderboardPage = React.lazy(() => import('./leaderboard'));
const ModelPage = React.lazy(() => import('./model'));
const ModelsDirectoryPage = React.lazy(() => import('./models-directory'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: true, staleTime: 2_000 },
    mutations: { retry: 0 },
  },
});

export function mount(): void {
  const rootElement = document.getElementById('root');
  if (!rootElement) throw new Error('Simulation root is missing');
  createRoot(rootElement).render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <SimulationShell>
            <Suspense fallback={<div className="page-loading" role="status">Loading this view…</div>}>
              <Routes>
                <Route path="/simulation" element={<DirectoryPage />} />
                <Route path="/simulation/:competitionId" element={<CompetitionPage />} />
                <Route path="/simulation/:competitionId/leaderboard" element={<LeaderboardPage />} />
                <Route path="/simulation/:competitionId/models" element={<ModelsDirectoryPage />} />
                <Route path="/simulation/:competitionId/models/:agentId" element={<ModelPage />} />
                <Route path="*" element={<Navigate to="/simulation" replace />} />
              </Routes>
            </Suspense>
          </SimulationShell>
        </BrowserRouter>
      </QueryClientProvider>
    </React.StrictMode>,
  );
}
