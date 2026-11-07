export type Unit = 'g' | 'count' | 'ml';

const COUNT_WORDS = ['egg', 'lemon', 'lime', 'apple', 'avocado', 'onion', 'pepper', 'tomato'];
const ML_WORDS = ['milk', 'juice', 'oil', 'cream', 'broth', 'soda'];
const NOT_A_UNIT = ['sour cream', 'cream cheese', 'ice cream', 'peppercorn', 'eggplant', 'pepper flake'];
const PLURAL_ES = new Set(['tomato', 'potato', 'mango']);

const hasWord = (text: string, stem: string) => new RegExp(`\\b${stem}(e?s)?\\b`).test(text);

/** Same guess as the backend (inventory/units.py): eggs are counted, milk is poured, the rest weighed. */
export function guessUnit(name: string): Unit {
  const text = name.toLowerCase();
  if (NOT_A_UNIT.some((w) => text.includes(w))) return 'g';
  if (COUNT_WORDS.some((w) => hasWord(text, w))) return 'count';
  if (ML_WORDS.some((w) => hasWord(text, w))) return 'ml';
  return 'g';
}

function singular(word: string): string {
  if (word.endsWith('ies')) return `${word.slice(0, -3)}y`;
  if (word.endsWith('oes')) return word.slice(0, -2);
  if (word.endsWith('s') && !word.endsWith('ss')) return word.slice(0, -1);
  return word;
}

function plural(word: string): string {
  if (PLURAL_ES.has(word)) return `${word}es`;
  if (/[^aeiou]y$/.test(word)) return `${word.slice(0, -1)}ies`;
  return `${word}s`;
}

/** "egg"/"eggs" from a product name like "Eggs" or "Large Brown Eggs"; leftovers are counted in servings. */
function countNoun(name: string | undefined, n: number): string {
  const last = name?.trim().toLowerCase().split(/\s+/).pop();
  const one = last === 'leftovers' ? 'serving' : last ? singular(last) : 'piece';
  return n === 1 ? one : plural(one);
}

const trim1 = (n: number) => (Math.round(n * 10) / 10).toString();

/**
 * An amount the way people say it: "6 eggs", "about 1 egg", "1 L", "250 ml", "150 g", "1.2 kg".
 * Stock is stored in grams; `unit` and `gramsPerUnit` come from the product.
 */
export function formatAmount(grams: number, unit: Unit = 'g', gramsPerUnit = 1, name?: string): string {
  if (unit === 'count') {
    const exact = grams / (gramsPerUnit || 1);
    const n = Math.round(exact);
    if (n < 1) return grams > 0 ? `less than 1 ${countNoun(name, 1)}` : `0 ${countNoun(name, 0)}`;
    const about = Math.abs(exact - n) > 0.15 ? 'about ' : '';
    return `${about}${n} ${countNoun(name, n)}`;
  }
  const amount = unit === 'ml' ? grams / (gramsPerUnit || 1) : grams;
  const [small, big] = unit === 'ml' ? ['ml', 'L'] : ['g', 'kg'];
  if (amount >= 1000) return `${trim1(amount / 1000)} ${big}`;
  const rounded = amount >= 100 && unit === 'ml' ? Math.round(amount / 10) * 10 : Math.round(amount);
  return `${rounded} ${small}`;
}

/** Converts an entered amount in the product's unit to grams. */
export const toGrams = (quantity: number, unit: Unit, gramsPerUnit: number) =>
  unit === 'g' ? quantity : quantity * gramsPerUnit;

/** The other way: grams to the product's unit (for editing). */
export const fromGrams = (grams: number, unit: Unit, gramsPerUnit: number) =>
  unit === 'g' ? Math.round(grams) : Math.round((grams / (gramsPerUnit || 1)) * 10) / 10;
