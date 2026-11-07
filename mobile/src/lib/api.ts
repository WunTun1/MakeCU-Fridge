import Constants from 'expo-constants';
import { Platform } from 'react-native';

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

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body) });

export type Alert = {
  product_id: number | null;
  product_name: string;
  reason: 'low_days_left' | 'low_fraction' | 'staple_out' | 'expiring_soon' | 'fridge_temp_high';
  detail: string;
};

export type InventoryEntry = {
  product_id: number;
  name: string;
  category: string | null;
  grams: number;
  package_size_g: number | null;
  days_left: number | null;
  fill_fraction: number | null;
  /** Soonest expiry among this product's items; null if none known. */
  expires_in_days: number | null;
  /** True when that date is an estimated shelf life, not printed on the package. */
  expiry_estimated: boolean;
  location: 'fridge' | 'pantry' | 'freezer';
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
  today_intake: { period: string; totals: Macros; meal_count: number };
  inventory: InventoryEntry[];
  review_queue_count: number;
  conditions: Conditions | null;
  door_open: boolean;
};

export type SearchResult = {
  product_id: number;
  product_name: string;
  on_hand_g: number;
  days_left: number | null;
  answer: string;
};

export type ProductUsage = {
  product_id: number;
  name: string;
  daily_usage_g: Record<string, number>;
  on_hand_g: number;
  days_left: number | null;
};

export type GroceryItem = {
  product_id: number;
  product_name: string;
  buy_grams: number;
  buy_packages: number | null;
  reason: string;
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
  missing: string[];
  swaps: Swap[];
  uses_expiring: string[];
  reasons: string[];
};

export type RecipeLine = {
  name: string;
  amount: string | null;
  status: 'have' | 'swap' | 'missing' | 'staple';
  use?: string;
  note?: string;
};

export type RecipeDetail = RecipeCard & {
  ingredients: RecipeLine[];
  steps: string[];
  description: string | null;
};

export type ChatReply = { reply: string; recipes: RecipeCard[] };

export type UnlockSuggestion = { buy: string[]; unlocks: number; examples: string[]; recipe_ids: number[] };

export const api = {
  summary: () => request<Summary>('/api/summary'),
  commonProducts: (limit = 8) => request<{ id: number; name: string }[]>(`/api/products/common?limit=${limit}`),
  search: (q: string) => request<SearchResult[]>(`/api/search?q=${encodeURIComponent(q)}`),
  usage: (productId: number) => request<ProductUsage>(`/api/products/${productId}/usage`),
  grocery: (tripInDays?: number) =>
    request<{ trip_date: string | null; items: GroceryItem[]; unlock: UnlockSuggestion[] }>(
      `/api/grocery${tripInDays != null ? `?trip_in_days=${tripInDays}` : ''}`,
    ),
  review: () => request<ReviewItem[]>('/api/review'),
  resolveReview: (
    id: number,
    body:
      | { action: 'ignore' }
      | { action: 'remove'; item_id: number }
      | { action: 'add_confirmed'; product_name: string; grams?: number },
  ) => post<{ ok: true }>(`/api/review/${id}`, body),
  addItem: (body: { name: string; grams: number; location: string }) =>
    post<{ item_id: number }>('/api/items', body),
  barcode: (barcode: string, location = 'pantry') =>
    post<{ item_id: number }>('/api/barcode', { barcode, location }),
  profile: () => request<Profile>('/api/profile'),
  saveProfile: (p: Partial<Profile>) =>
    request<{ ok: true }>('/api/profile', { method: 'PUT', body: JSON.stringify(p) }),
  chat: (message: string) => post<ChatReply>('/api/chat', { message }),
  taste: () => request<{ cuisines: string[]; ingredients: string[] }>('/api/taste'),
  suggestRecipes: (params: { q?: string; cuisine?: string; high_protein?: boolean; max_minutes?: number; limit?: number }) => {
    const qs = Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== '' && v !== false)
      .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
      .join('&');
    return request<RecipeCard[]>(`/api/recipes/suggest${qs ? `?${qs}` : ''}`);
  },
  recipe: (id: number) => request<RecipeDetail>(`/api/recipes/${id}`),
  cooked: (id: number, servingsEaten: number) =>
    post<{ recipe: string; used: { item: string; grams: number }[] }>(`/api/recipes/${id}/cooked`, { servings_eaten: servingsEaten }),
  rate: (id: number, liked: boolean) => post<{ ok: true }>(`/api/recipes/${id}/rate`, { liked }),
};
