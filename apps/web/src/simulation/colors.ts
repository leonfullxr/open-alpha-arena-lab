import type { Agent } from './api';

/** Fallback slots cover providers without a named model palette entry. */
const MODEL_PALETTE = ['#3467ff', '#ec4899', '#00a98f', '#f97316', '#8b5cf6', '#4f46e5', '#168bff', '#111111'];

const NAMED_MODEL_SLOTS = [
  { pattern: /grok[-_ ]?4[._ -]?20/i, slot: 1 },
  { pattern: /gpt[-_ ]?5\.1/i, slot: 2 },
  { pattern: /qwen/i, slot: 4 },
  { pattern: /kimi/i, slot: 6 },
  { pattern: /deepseek/i, slot: 5 },
  { pattern: /gemini/i, slot: 0 },
  { pattern: /claude/i, slot: 3 },
  { pattern: /grok\s*4|grok[-_ ]?4/i, slot: 7 },
] as const;

export function agentIndex(agents: Agent[], agentId: string): number {
  const index = agents.findIndex((agent) => agent.id === agentId);
  return index < 0 ? 0 : index;
}

export function modelColor(agents: Agent[], agentId: string): string {
  const agent = agents.find((item) => item.id === agentId);
  return MODEL_PALETTE[namedModelSlot(agent) ?? agentIndex(agents, agentId) % MODEL_PALETTE.length]!;
}

export function modelToneClass(agents: Agent[], agentId: string): string {
  const agent = agents.find((item) => item.id === agentId);
  return `model-tone-${namedModelSlot(agent) ?? agentIndex(agents, agentId) % MODEL_PALETTE.length}`;
}

function namedModelSlot(agent: Agent | undefined): number | undefined {
  if (!agent) return undefined;
  const identity = `${agent.provider} ${agent.model} ${agent.name}`;
  return NAMED_MODEL_SLOTS.find(({ pattern }) => pattern.test(identity))?.slot;
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
