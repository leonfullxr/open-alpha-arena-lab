import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AdminApp } from './site';
import './admin.css';

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 0, refetchOnWindowFocus: true }, mutations: { retry: 0 } } });

const root = document.getElementById('admin-root');
if (!root) throw new Error('Admin root is missing');
createRoot(root).render(<React.StrictMode><QueryClientProvider client={queryClient}><AdminApp /></QueryClientProvider></React.StrictMode>);
