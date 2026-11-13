/**
 * Cost estimation.
 *
 * The price table ships empty on purpose. A cost appears only when one of these is true:
 *   1. the backend reports TokenUsage.estimatedCostUsd for the run, or
 *   2. someone has entered the per-token prices of the model actually in use
 *      (docs/submission/COST_PER_RUN.md explains where to get them).
 * Until then every cost is null and the UI shows a placeholder.
 */
import type { TokenUsage } from '../api/types';

export interface ModelPrice {
  /** USD per one million uncached input tokens. */
  inputPerMTokUsd: number;
  /** USD per one million output tokens. */
  outputPerMTokUsd: number;
  /** USD per one million cached input tokens. Falls back to the input price when absent. */
  cachedInputPerMTokUsd?: number;
}

/** Keyed by TokenUsage.model, exactly as the backend reports it. */
export type PriceTable = Record<string, ModelPrice>;

export const DEFAULT_PRICE_TABLE: PriceTable = {};

/**
 * TokenUsage.inputTokens counts uncached input only; cachedInputTokens is billed separately.
 * Returns null when the model has no entry in the table.
 */
export function costFromPriceTable(usage: TokenUsage, table: PriceTable): number | null {
  const price = table[usage.model];
  if (!price) return null;
  const cached = usage.cachedInputTokens ?? 0;
  return (
    (usage.inputTokens * price.inputPerMTokUsd +
      usage.outputTokens * price.outputPerMTokUsd +
      cached * (price.cachedInputPerMTokUsd ?? price.inputPerMTokUsd)) /
    1_000_000
  );
}

export function estimateCost(usage: TokenUsage | null, table: PriceTable): { usd: number | null; source: 'backend' | 'price_table' | null } {
  if (!usage) return { usd: null, source: null };
  // A missing field is not a price of zero: only a number the backend actually sent counts.
  if (typeof usage.estimatedCostUsd === 'number' && Number.isFinite(usage.estimatedCostUsd)) return { usd: usage.estimatedCostUsd, source: 'backend' };
  const usd = costFromPriceTable(usage, table);
  return { usd, source: usd === null ? null : 'price_table' };
}

export function parsePriceTable(value: unknown): PriceTable {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('A price table must be a JSON object keyed by model name.');
  const table: PriceTable = {};
  for (const [model, raw] of Object.entries(value as Record<string, unknown>)) {
    const price = raw as Partial<ModelPrice>;
    if (typeof price?.inputPerMTokUsd !== 'number' || typeof price?.outputPerMTokUsd !== 'number') {
      throw new Error(`Price for "${model}" needs numeric inputPerMTokUsd and outputPerMTokUsd.`);
    }
    table[model] = {
      inputPerMTokUsd: price.inputPerMTokUsd,
      outputPerMTokUsd: price.outputPerMTokUsd,
      ...(typeof price.cachedInputPerMTokUsd === 'number' ? { cachedInputPerMTokUsd: price.cachedInputPerMTokUsd } : {}),
    };
  }
  return table;
}
