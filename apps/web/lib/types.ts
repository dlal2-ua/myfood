export type Sex = "male" | "female";
export type ActivityLevel = "sedentary" | "light" | "moderate" | "active" | "very_active";
export type Goal = "lose" | "maintain" | "gain";
export type BmrFormula = "mifflin" | "katch" | "cunningham" | "harris";

export interface Profile {
  sex: Sex | null;
  birth_date: string | null;
  height_cm: number | null;
  activity_level: ActivityLevel;
  goal: Goal;
  goal_rate_kg_week: number | null;
  bmr_formula: BmrFormula;
  meals_per_day: number;
  budget_eur_week: number | null;
  max_cook_minutes: number | null;
  diet_style: string | null;
}

export type ProfileUpdate = Partial<Profile>;

export type BfMethod = "navy" | "jackson3" | "jackson7" | "durnin" | "bia" | "manual";
export type MeasurementSource = "manual" | "health_connect" | "scale";

export interface Measurement {
  id?: string;
  measured_on: string;
  weight_kg: number | null;
  body_fat_pct: number | null;
  bf_method: BfMethod | null;
  neck_cm: number | null;
  waist_cm: number | null;
  hip_cm: number | null;
  chest_cm: number | null;
  arm_cm: number | null;
  thigh_cm: number | null;
  source: MeasurementSource;
}

export interface BmrResponse {
  bmr: number;
  tdee: number;
  formula_used: string;
}

export interface TargetsResponse {
  kcal: number;
  protein_g: number;
  fat_g: number;
  carbs_g: number;
  water_ml: number;
  source: "formula" | "adaptive_tdee";
  warnings: string[];
}

export const MEAL_TYPES = [
  "breakfast",
  "morning_snack",
  "lunch",
  "afternoon_snack",
  "dinner",
  "supper",
] as const;
export type MealType = (typeof MEAL_TYPES)[number];

export const MEAL_TYPE_LABELS: Record<MealType, string> = {
  breakfast: "Desayuno",
  morning_snack: "Media mañana",
  lunch: "Comida",
  afternoon_snack: "Merienda",
  dinner: "Cena",
  supper: "Recena",
};

export interface FoodSearchItem {
  id: string;
  name_es: string;
  brand: string | null;
  kcal_100g: number | null;
  protein_100g: number | null;
  image_url: string | null;
  source: string;
}

export interface FoodSearchResponse {
  items: FoodSearchItem[];
  total: number;
}

export interface FoodDetail {
  id: string;
  kind: string;
  source: string;
  license: string;
  attribution: string | null;
  barcode_ean: string | null;
  name_es: string;
  name_en: string | null;
  brand: string | null;
  category: string | null;
  serving_size_g: number | null;
  serving_label: string | null;
  quality_rank: number;
  nutriscore_grade: string | null;
  nova_group: number | null;
  ecoscore_grade: string | null;
  kcal_100g: number;
  protein_100g: number;
  fat_100g: number;
  saturated_100g: number | null;
  carbs_100g: number;
  sugars_100g: number | null;
  fiber_100g: number | null;
  salt_100g: number | null;
  micros: Record<string, number>;
}

export interface LogFoodEntry {
  id: string;
  log_date: string;
  meal_type: MealType;
  food_id: string | null;
  grams: number;
  entry_source: string;
  kcal: number;
  protein_g: number;
  fat_g: number;
  carbs_g: number;
}

export interface DayTotals {
  kcal: number;
  protein_g: number;
  fat_g: number;
  carbs_g: number;
}

export interface LogDay {
  date: string;
  food: LogFoodEntry[];
  totals: DayTotals;
}

export interface Favorite {
  id: string;
  food_id: string;
  name_es: string;
  brand: string | null;
  kcal_100g: number | null;
  use_count: number;
  last_used_at: string | null;
}

export interface FavoriteList {
  items: Favorite[];
}

export interface ShoppingListItem {
  id: string;
  food_id: string | null;
  food_name: string | null;
  free_text: string | null;
  quantity_g: number | null;
  category: string | null;
  is_checked: boolean;
}

export interface ShoppingList {
  items: ShoppingListItem[];
}

export interface Supplement {
  id: string;
  name: string;
  type: string;
  dose_amount: number;
  dose_unit: string;
  doses_per_container: number | null;
  price_per_container: number | null;
  notes: string | null;
  is_active: boolean;
  food_id: string | null;
  created_at: string;
  doses_remaining: number | null;
  last_restock_at: string | null;
  days_remaining: number | null;
  low_stock: boolean;
}

export interface SupplementList {
  items: Supplement[];
}

export interface SupplementSchedule {
  id: string;
  time_of_day: string;
  days_of_week: number[];
  with_food: boolean;
}

export interface SupplementDetail extends Supplement {
  schedules: SupplementSchedule[];
}

export interface SupplementLogEntry {
  id: string;
  supplement_id: string;
  supplement_name: string;
  log_date: string;
  taken_at: string;
  skipped: boolean;
}
