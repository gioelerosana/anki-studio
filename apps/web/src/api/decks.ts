import type { DeckNode } from './types';

export function findDeck(nodes: DeckNode[], id: number): DeckNode | null {
  for (const node of nodes) {
    if (node.id === id) return node;
    const found = findDeck(node.children, id);
    if (found) return found;
  }
  return null;
}

/** Tutti i mazzi in ordine di albero, per i menu a tendina. */
export function flattenDecks(nodes: DeckNode[]): DeckNode[] {
  return nodes.flatMap((n) => [n, ...flattenDecks(n.children)]);
}
