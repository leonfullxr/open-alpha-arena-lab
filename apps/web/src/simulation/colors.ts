import type { Agent } from './api';

/**
 * One palette drives every place a model appears: chart series, chat cards,
 * account rows and model pages. The colour is chosen from the agent's position
 * in the competition's published account list, so the same account keeps the
 * same colour everywhere.
 */
const MODEL_PALETTE = ['#2e6f9e', '#b0373c', '#2b7a4f', '#c05f18', '#6a5aae', '#9a7c14', '#157f86', '#a4407c'];

export function agentIndex(agents: Agent[], agentId: string): number {
  const index = agents.findIndex((agent) => agent.id === agentId);
  return index < 0 ? 0 : index;
}

export function modelColor(agents: Agent[], agentId: string): string {
  return MODEL_PALETTE[agentIndex(agents, agentId) % MODEL_PALETTE.length]!;
}

export function modelToneClass(agents: Agent[], agentId: string): string {
  return `model-tone-${agentIndex(agents, agentId) % MODEL_PALETTE.length}`;
}

/** Marker glyph shown at the left edge of a chat card. One shape per model. */
export const MODEL_MARKERS = ['✳', '◆', '▲', '●', '■', '✶', '▼', '⬟'];

export function modelMarker(agents: Agent[], agentId: string): string {
  return MODEL_MARKERS[agentIndex(agents, agentId) % MODEL_MARKERS.length]!;
}

/** Short, publication-safe label for a run profile. */
export function profileTag(profile: string): string {
  const short = profile.replace(/^alpha_2025_/, '').replace(/^research_/, '').replace(/_/g, ' ');
  return short.toUpperCase() || profile.toUpperCase();
}
