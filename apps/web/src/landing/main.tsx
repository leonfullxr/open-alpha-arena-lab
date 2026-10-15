import React from 'react';
import { createRoot } from 'react-dom/client';
import { ArenaLanding } from '../site';
import '../styles.css';

export function mount(): void {
  const root = document.getElementById('root');
  if (!root) throw new Error('Landing root is missing');
  createRoot(root).render(<React.StrictMode><ArenaLanding /></React.StrictMode>);
}
