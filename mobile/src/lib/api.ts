import Constants from 'expo-constants';
import { Platform } from 'react-native';

const BACKEND_PORT = 8000;

// Phone (Expo Go): "localhost" is the phone itself, so use the LAN host serving the JS bundle.
// Web (the fridge screen, or `expo start --web`): the backend lives on the same host the page came from.
function resolveBaseUrl(): string {
  const explicit = process.env.EXPO_PUBLIC_API_URL;
  if (explicit) return explicit.replace(/\/$/, '');
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    return `${window.location.protocol}//${window.location.hostname}:${BACKEND_PORT}`;
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
  if (!res.ok) throw new Error(`${init?.method ?? 'GET'} ${path} failed: ${res.status}`);
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

export type Activity = {
  id: number;
  event_type: 'add' | 'remove' | 'consume' | 'return' | 'waste';
  grams_delta: number;
  shelf: number | null;
  occurred_at: string;
  product_name: string;
};

export const api = {
  summary: () => request<Summary>('/api/summary'),
  activity: (limit = 8) => request<Activity[]>(`/api/activity?limit=${limit}`),
  commonProducts: (limit = 8) => request<{ id: number; name: string }[]>(`/api/products/common?limit=${limit}`),
  search: (q: string) => request<SearchResult[]>(`/api/search?q=${encodeURIComponent(q)}`),
  usage: (productId: number) => request<ProductUsage>(`/api/products/${productId}/usage`),
  grocery: (tripInDays?: number) =>
    request<{ trip_date: string | null; items: GroceryItem[] }>(
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
  chat: (message: string) => post<{ reply: string }>('/api/chat', { message }),
};
