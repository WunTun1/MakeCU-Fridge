import Constants from 'expo-constants';
import { Platform } from 'react-native';

import type { Unit } from '@/lib/amount';

const BACKEND_PORT = 8000;
const EXPO_DEV_PORTS = new Set(['8081', '19006']);

// Phone (Expo Go): "localhost" is the phone itself, so use the LAN host serving the JS bundle.
// Web served by the backend (the fridge screen): same origin, whatever port that is.
// Web from the Expo dev server (`expo start --web`): same host, backend port.
function resolveBaseUrl(): string {
  const explicit = process.env.EXPO_PUBLIC_API_URL;
  if (explicit) return explicit.replace(/\/$/, '');
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    const { protocol, hostname, port, origin } = window.location;
    return EXPO_DEV_PORTS.has(port) ? `${protocol}//${hostname}:${BACKEND_PORT}` : origin;
  }
  const devHost = Constants.expoConfig?.hostUri?.split(':')[0];
  return `http://${devHost ?? 'localhost'}:${BACKEND_PORT}`;
}

export const API_URL = resolveBaseUrl();

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!res.ok) {
    // FastAPI errors carry a human-readable {"detail": "..."} — show that, not just the status code.
    const detail = await res
      .json()
      .then((b: { detail?: unknown }) => (typeof b?.detail === 'string' ? b.detail : null))
      .catch(() => null);
    throw new Error(detail ?? `${init?.method ?? 'GET'} ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) });
const patch = <T>(path: string, body: unknown) => request<T>(path, { method: 'PATCH', body: JSON.stringify(body) });
const del = <T>(path: string) => request<T>(path, { method: 'DELETE' });

export type Alert = {
  product_id: number | null;
  product_name: string;
  reason: 'low_days_left' | 'low_fraction' | 'staple_out' | 'expiring_soon' | 'fridge_temp_high';
  detail: string;
  /** Days until it goes bad (expiring_soon) or runs out (low_days_left). */
  days: number | null;
};

export type Location = 'fridge' | 'pantry' | 'freezer';

/** How a product is counted; stock is always stored in grams. */
export type Measured = { unit: Unit; grams_per_unit: number };

export type InventoryEntry = Measured & {
  product_id: number;
  name: string;
  category: string | null;
  grams: number;
  package_size_g: number | null;
  days_left: number | null;
  fill_fraction: number | null;
  /** Soonest expiry among this product's items, in the household's days; null if none known. */
  expires_in_days: number | null;
  /** Grams you won't have used by the day it goes bad; null when you'll finish it first. */
  likely_wasted_g: number | null;
  /** True when that date is an estimated shelf life, not printed on the package. */
  expiry_estimated: boolean;
  /** The package(s) that go bad first; less than `grams` when newer packages are there too. */
  soonest_batch: { grams: number; expiration_date: string; expires_in_days: number } | null;
  /** A product with packages in the freezer and elsewhere has one entry for each. */
  location: Location;
  /** 0-based shelf index; null for pantry items or ones not placed on a shelf. */
  shelf: number | null;
  /** Cooked food from a recipe, counted in servings. */
  leftovers: boolean;
};

export type Macros = { calories: number; protein_g: number; carbs_g: number; fat_g: number };

export type Conditions = {
  occurred_at: string;
  temperature_c: number | null;
  pressure_hpa: number | null;
  humidity_pct: number | null;
  light_raw: number | null;
};

export type Summary = {
  alerts: Alert[];
  next_trip_date: string | null;
  next_trip_in_days: number | null;
  /** What the grocery list buys lasts until this date. */
  covers_until: string | null;
  today_intake: { period: string; totals: Macros; meal_count: number };
  inventory: InventoryEntry[];
  review_queue_count: number;
  conditions: Conditions | null;
  door_open: boolean;
};

export type SearchResult = Measured & {
  product_id: number;
  product_name: string;
  on_hand_g: number;
  days_left: number | null;
  answer: string;
  /** Soonest goes-bad date among packages outside the freezer. */
  expires_in_days: number | null;
  likely_wasted_g: number | null;
};

export type StockItem = {
  id: number;
  grams: number;
  location: Location;
  expiration_date: string | null;
  expiry_estimated: boolean;
  expires_in_days: number | null;
};

export type ProductUsage = Measured & {
  product_id: number;
  name: string;
  category: string | null;
  /** Leftovers: the recipe they were cooked from. */
  recipe_id: number | null;
  daily_usage_g: Record<string, number>;
  on_hand_g: number;
  days_left: number | null;
  rate_g_per_day: number;
  /** The soonest date on its Home row (outside the freezer when some is). */
  expiration_date: string | null;
  expiry_estimated: boolean;
  expires_in_days: number | null;
  likely_wasted_g: number | null;
  items: StockItem[];
};

/** Why the restock plan wants something. */
export type GroceryPlan = {
  product_id: number;
  product_name: string;
  buy_grams: number;
  buy_packages: number | null;
  on_hand_g: number;
  rate_g_per_day: number;
  runs_out_in_days: number | null;
};

export type GroceryEntry = Measured & {
  id: number;
  name: string;
  /** "6", "2 L": how much, when the person said so. */
  amount: string | null;
  source: 'plan' | 'manual' | 'recipe';
  recipe_id: number | null;
  recipe_name: string | null;
  checked: boolean;
  plan: GroceryPlan | null;
};

export type Horizon = 1 | 3 | 7 | null;

export type GroceryList = {
  trip_in_days: Horizon;
  trip_date: string | null;
  trip_days_away: number | null;
  covers_until: string | null;
  items: GroceryEntry[];
};

export type ReviewItem = {
  id: number;
  item_id: number | null;
  product_id: number | null;
  shelf: number | null;
  occurred_at: string;
  meta: Record<string, unknown> | null;
};

export type Profile = {
  daily_calories: number | null;
  daily_protein_g: number | null;
  daily_carbs_g: number | null;
  daily_fat_g: number | null;
  diet_type: string | null;
  allergies: string[];
  dislikes: string[];
  /** Protein is at least 25% of the calorie goal: recipe lists rank by protein. */
  protein_mode: boolean;
};

export type Nutrition = {
  calories: number | null;
  protein_g: number | null;
  fat_g: number | null;
  carbs_g: number | null;
  fiber_g: number | null;
  sugar_g: number | null;
  sodium_mg: number | null;
};

export type Swap = { missing: string; use: string; note: string };

/** "fresh spinach" with on_hand "150 g"; `use` when it's a swap you're short of. */
export type ShortLine = { name: string; on_hand: string; use?: string };

/** A real recipe from the library, scored against what's in your fridge. */
export type RecipeCard = {
  id: number;
  name: string;
  cuisine: string | null;
  minutes: number | null;
  servings: number | null;
  image_url: string | null;
  nutrition: Nutrition;
  have_count: number;
  /** Some on hand, not enough for the recipe. */
  short: ShortLine[];
  missing: string[];
  swaps: Swap[];
  uses_expiring: string[];
  reasons: string[];
};

export type RecipeLine = {
  name: string;
  amount: string | null;
  status: 'have' | 'short' | 'swap' | 'missing' | 'staple';
  /** Short lines: how much you have, e.g. "150 g". */
  on_hand?: string;
  use?: string;
  note?: string;
};

export type RecipeDetail = RecipeCard & {
  ingredients: RecipeLine[];
  steps: string[];
  description: string | null;
  /** Missing or short ingredients that are already on the grocery list. */
  on_grocery_list: string[];
  /** Servings of it in the fridge from an earlier cook. */
  leftovers: { product_id: number; servings: number } | null;
  /** Cooked and logged today. */
  logged_meal_id: number | null;
};

/** One product an "I made this" takes from. */
export type CookLine = Measured & { product_id: number; item: string; grams_used: number; grams_on_hand: number };

/** How much of the recipe was cooked: all of it or half. */
export type Made = 1 | 0.5;

/** A reply that changed stock has a turn id and an Undo label ("Undo: puts back 400 g chicken breast"). */
export type ChatReply = { reply: string; recipes: RecipeCard[]; turn_id: number | null; undo: string | null };

/** A logged meal; a macro is null when nothing was known about it. */
export type Meal = { [K in keyof Macros]: number | null } & {
  id: number;
  name: string | null;
  servings: number;
  occurred_at: string;
  source: string;
  /** Cooked with "I made this": what undoing the cooking puts back and removes. */
  cook_undo: string | null;
};

/** Ate some of a fridge item as it is; what it logged. */
export type Eaten = Pick<Meal, keyof Macros> & { meal_id: number; grams: number };

/** A portion of a fridge item worth logging for protein: "Greek yogurt 200 g", "2 eggs". */
export type QuickAdd = Measured & { product_id: number; name: string; grams: number; protein_g: number; calories: number | null };

export type UnlockSuggestion = { buy: string[]; unlocks: number; examples: string[]; recipe_ids: number[] };

export const api = {
  summary: () => request<Summary>('/api/summary'),
  commonProducts: (limit = 8) => request<{ id: number; name: string }[]>(`/api/products/common?limit=${limit}`),
  search: (q: string) => request<SearchResult[]>(`/api/search?q=${encodeURIComponent(q)}`),
  usage: (productId: number) => request<ProductUsage>(`/api/products/${productId}/usage`),
  grocery: () => request<GroceryList>('/api/grocery'),
  setHorizon: (tripInDays: Horizon) => request<GroceryList>('/api/grocery/horizon', { method: 'PUT', body: JSON.stringify({ trip_in_days: tripInDays }) }),
  addToGrocery: (body: { names: string[]; source?: 'manual' | 'recipe'; recipe_id?: number; recipe_name?: string }) =>
    post<{ ids: number[] }>('/api/grocery/items', body),
  checkGrocery: (id: number, checked: boolean) => patch<{ ok: true }>(`/api/grocery/items/${id}`, { checked }),
  /** Removes a row (or brings it back); an automatic row stays off for this trip. */
  hideGrocery: (id: number, hidden: boolean) => patch<{ ok: true }>(`/api/grocery/items/${id}`, { hidden }),
  clearCheckedGrocery: () => post<{ ok: true }>('/api/grocery/clear-checked', {}),
  unlock: () => request<UnlockSuggestion[]>('/api/grocery/unlock'),
  review: () => request<ReviewItem[]>('/api/review'),
  resolveReview: (
    id: number,
    body:
      | { action: 'ignore' }
      | { action: 'remove'; item_id: number }
      | { action: 'add_confirmed'; product_name: string; grams?: number },
  ) => post<{ ok: true }>(`/api/review/${id}`, body),
  addItem: (body: { name: string; quantity: number; unit: Unit | 'lb' | 'oz'; location: string }) =>
    post<Measured & { item_id: number; product_id: number; grams: number; checked_off: { id: number; name: string } | null }>(
      '/api/items',
      body,
    ),
  undoAdd: (itemId: number) => post<{ ok: true }>(`/api/items/${itemId}/undo-add`, {}),
  updateItem: (itemId: number, body: { grams?: number; expiration_date?: string }) => patch<{ ok: true }>(`/api/items/${itemId}`, body),
  consume: (itemId: number, grams: number) => post<{ event_id: number | null }>('/api/items/consume', { item_id: itemId, grams }),
  waste: (itemIds: number[]) => post<{ event_ids: number[] }>('/api/items/waste', { item_ids: itemIds }),
  undoEvents: (eventIds: number[]) => post<{ ok: true }>('/api/events/undo', { event_ids: eventIds }),
  barcode: (barcode: string, location = 'pantry') => post<{ item_id: number }>('/api/barcode', { barcode, location }),
  profile: () => request<Profile>('/api/profile'),
  saveProfile: (p: Partial<Profile>) => request<{ ok: true }>('/api/profile', { method: 'PUT', body: JSON.stringify(p) }),
  chat: (message: string) => post<ChatReply>('/api/chat', { message }),
  clearChat: () => del<{ ok: true }>('/api/chat/history'),
  /** Reverses everything one chat reply changed. */
  undoTurn: (turnId: number) => post<{ ok: true }>(`/api/chat/turns/${turnId}/undo`, {}),
  taste: () => request<{ cuisines: string[]; ingredients: string[] }>('/api/taste'),
  /** Cook tonight: dinner-sized main dishes from what you have (cached on the server). */
  tonight: () => request<RecipeCard[]>('/api/recipes/tonight'),
  recipe: (id: number) => request<RecipeDetail>(`/api/recipes/${id}`),
  cookPreview: (id: number, made: Made) => request<CookLine[]>(`/api/recipes/${id}/cooked/preview?made=${made}`),
  cooked: (id: number, made: Made, servingsEaten: number) =>
    post<{
      recipe: string;
      meal_id: number;
      consumptions: CookLine[];
      leftovers: { product_id: number; servings: number; expiration_date: string } | null;
    }>(`/api/recipes/${id}/cooked`, { made, servings_eaten: servingsEaten }),
  /** Takes back a meal and everything it did to the fridge. */
  undoMeal: (mealId: number) => post<{ ok: true }>(`/api/meals/${mealId}/undo`, {}),
  meals: () => request<Meal[]>('/api/meals?period=today'),
  /** Nutrition only (numbers off a label); with occurred_at, puts back a removed meal. */
  addMeal: (body: Partial<Omit<Meal, 'id' | 'cook_undo'>> & { name: string }) => post<{ meal_id: number }>('/api/meals', body),
  /** Off today's log only; the fridge stays as it is. Returns the meal for Undo. */
  deleteMeal: (mealId: number) => del<Omit<Meal, 'id' | 'cook_undo'>>(`/api/meals/${mealId}`),
  quickAdds: () => request<QuickAdd[]>('/api/meals/quick-adds'),
  /** Ate it as it is: one serving of leftovers, or `grams` of anything. */
  eat: (productId: number, grams?: number) => post<Eaten>(`/api/products/${productId}/eat`, { grams }),
  freeze: (productId: number) =>
    post<{ event_ids: number[]; grams: number; expiration_date: string }>(`/api/products/${productId}/freeze`, {}),
  rate: (id: number, liked: boolean) => post<{ ok: true }>(`/api/recipes/${id}/rate`, { liked }),
};
