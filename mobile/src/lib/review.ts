import type { ReviewItem } from '@/lib/api';
import { formatGrams } from '@/lib/theme';

export type ReviewMeta = {
  note?: string;
  reason?: string;
  grams?: number;
  total_grams?: number;
  candidate?: { item_name?: string; confidence?: number };
};

export const metaOf = (r: ReviewItem) => (r.meta ?? {}) as ReviewMeta;

/** Something new appeared that the camera couldn't name confidently. */
export function isUnnamedAdd(r: ReviewItem): boolean {
  const meta = metaOf(r);
  return r.item_id == null && meta.candidate != null && meta.grams != null;
}

/** The model's guess, unless it's the no-API-key placeholder. */
export function candidateName(r: ReviewItem): string | null {
  const name = metaOf(r).candidate?.item_name;
  return name && name !== 'Unknown Item' ? name : null;
}

export function describeReview(r: ReviewItem): string {
  const meta = metaOf(r);
  if (isUnnamedAdd(r)) return `New item, ${formatGrams(meta.grams!)} — what is it?`;
  const grams = meta.grams ?? meta.total_grams;
  const parts = [
    meta.note ?? meta.reason,
    grams != null && formatGrams(grams),
    r.shelf != null && `shelf ${r.shelf}`,
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : 'Uncertain fridge change';
}
