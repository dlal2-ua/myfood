import type { Portion } from "@/lib/portions";

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
  /** Declaraciones que desactivan la sugerencia de suplementos con IA. */
  is_pregnant_or_nursing: boolean;
  has_medical_condition: boolean;
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
  bmr_formula: BmrFormula;
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
  fat_100g?: number | null;
  carbs_100g?: number | null;
  image_url: string | null;
  source: string;
  nutriscore_grade?: string | null;
  nova_group?: number | null;
  ecoscore_grade?: string | null;
  /** Nombres para mostrar (no códigos). */
  supermarket?: string | null;
  food_type?: string | null;
}

export interface FacetOption {
  code: string;
  label: string;
  /** Alimentos que quedarían con esta opción dados los demás filtros elegidos. */
  count: number;
  description?: string | null;
}

export interface FoodFacets {
  supermarket: FacetOption[];
  food_type: FacetOption[];
  nutrition: FacetOption[];
}

export interface FoodSearchResponse {
  items: FoodSearchItem[];
  total: number;
  facets?: FoodFacets | null;
}

export interface SuggestionSection {
  key: string;
  title: string;
  subtitle: string | null;
  items: FoodSearchItem[];
}

export interface SuggestionsResponse {
  sections: SuggestionSection[];
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
  /** gramos cocido / gramos crudo; si lo tiene se puede registrar el peso ya cocinado. */
  cooking_yield_factor?: number | null;
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
  allergens: FoodAllergen[];
  /** Atribución obligatoria de la imagen (Open Food Facts, CC BY-SA), si tiene. */
  image_credit: string | null;
  /** Medidas caseras con las que registrarlo («1 huevo», «1 vaso», «100 g»). Los gramos de
   * cada una los pone el servidor (R1); la pantalla solo multiplica por la cantidad. */
  portions: Portion[];
  /** Cantidad propuesta al abrir el formulario, en gramos. */
  default_grams: number;
}

/** origin: 'declared' (etiqueta del fabricante), 'trace' ("puede contener") o
 * 'inferred' (alimento genérico clasificado por palabras clave: orientativo). */
export interface FoodAllergen {
  code: string;
  name_es: string;
  origin: "declared" | "trace" | "inferred";
}

export interface Allergen {
  code: string;
  name_es: string;
}

export type RestrictionKind = "allergen" | "intolerance" | "disliked_food" | "banned_food";

export interface Restriction {
  id: string;
  kind: RestrictionKind;
  allergen_code: string | null;
  allergen_name: string | null;
  food_id: string | null;
  food_name: string | null;
  note: string | null;
}

export interface LogFoodEntry {
  id: string;
  log_date: string;
  meal_type: MealType;
  food_id: string | null;
  recipe_id?: string | null;
  recipe_name?: string | null;
  food_name?: string | null;
  grams: number;
  /** "cooked": el usuario pesó el plato ya cocinado; `grams` es el peso crudo equivalente. */
  weighed_as?: "raw" | "cooked";
  entered_grams?: number | null;
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

export interface Micronutrient {
  key: string;
  label: string;
  amount: number;
  unit: string;
  reference: number;
  pct_of_reference: number;
}

export interface MicronutrientsDay {
  date: string;
  nutrients: Micronutrient[];
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
  owner_name: string;
  is_mine: boolean;
}

export interface ShoppingList {
  items: ShoppingListItem[];
}

export interface PrivacySummary {
  account_created_at: string;
  measurements_count: number;
  food_log_entries: number;
  water_log_entries: number;
  supplements_count: number;
  diet_plans_count: number;
  recipes_count: number;
}

export interface PantryItem {
  id: string;
  food_id: string;
  food_name: string;
  quantity_g: number;
  expires_on: string | null;
  owner_name: string;
  is_mine: boolean;
}

export interface HouseholdMemberInfo {
  user_id: string;
  display_name: string;
  email: string;
  joined_at: string;
}

export interface Household {
  id: string;
  name: string;
  invite_code: string;
  members: HouseholdMemberInfo[];
}

export type WaterMode = "auto" | "manual";

export interface WaterContainer {
  label: string;
  ml: number;
}

export interface WaterSettings {
  mode: WaterMode;
  daily_target_ml: number;
  containers: WaterContainer[];
}

export interface WaterLogEntry {
  id: string;
  log_date: string;
  ml: number;
}

export interface WaterDay {
  date: string;
  entries: WaterLogEntry[];
  total_ml: number;
  target_ml: number;
}

export interface NotificationRule {
  id: string;
  kind: "water" | "supplement" | "meal" | "weigh_in";
  is_enabled: boolean;
  schedule: Record<string, unknown>;
  quiet_from: string;
  quiet_to: string;
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
  /** Coste estimado de 30 días; null si falta el precio, las dosis del envase o un horario. */
  monthly_cost: number | null;
  image_url?: string | null;
}

export interface SupplementList {
  items: Supplement[];
  total_monthly_cost: number | null;
}

export interface SupplementSchedule {
  id: string;
  time_of_day: string;
  days_of_week: number[];
  with_food: boolean;
  has_reminder: boolean;
}

export interface TodayDose {
  supplement_id: string;
  supplement_name: string;
  dose_amount: number;
  dose_unit: string;
  schedule_id: string;
  time_of_day: string;
  with_food: boolean;
  status: "taken" | "skipped" | "pending" | "overdue";
}

export interface SupplementsToday {
  date: string;
  doses: TodayDose[];
  pending_count: number;
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

export interface DayMacroTotals {
  kcal: number;
  protein_g: number;
  fat_g: number;
  carbs_g: number;
}

export interface PlanItemAlternative {
  id: string;
  food_id: string;
  name_es: string;
  grams: number;
  rank: number;
  distance: number;
}

export interface PlanItem {
  id: string;
  food_id: string | null;
  recipe_id: string | null;
  name_es: string | null;
  grams: number;
  is_substitutable: boolean;
  alternatives: PlanItemAlternative[];
}

export interface PlanMeal {
  id: string;
  meal_type: MealType;
  items: PlanItem[];
}

export interface PlanDay {
  id: string;
  day_index: number;
  meals: PlanMeal[];
  totals: DayMacroTotals;
  /** `TARGETS_NOT_MET`: las kcal del día quedan a más de un 5 % del objetivo. */
  warning: string | null;
  /** `false`: el solver agotó el tiempo y esta es la mejor solución que encontró. */
  is_optimal: boolean;
}

export type DietPlanStatus = "draft" | "active" | "archived";

export interface DietPlan {
  id: string;
  name: string;
  start_date: string;
  end_date: string | null;
  status: DietPlanStatus;
  target_kcal: number;
  target_protein_g: number;
  target_fat_g: number;
  target_carbs_g: number;
  generated_by: string;
}

export interface DietPlanDetail extends DietPlan {
  days: PlanDay[];
}

export interface AiCredentialStatus {
  configured: boolean;
  provider: string | null;
  updated_at: string | null;
}

export interface IafoodLimits {
  per_profile_daily: number;
  instance_daily: number;
  max_tokens_per_call: number;
}

/** Cuánta cuota de iafood le queda hoy al usuario (`GET /ai/quota`). Se consulta sin
 * gastar nada: la cuota se descuenta al ENVIAR, así que la pantalla la enseña antes. */
export interface AiQuota {
  scope: string;
  used: number;
  limit: number;
  remaining: number;
  reset_at: string;
  /** Tope compartido por toda la casa; `null` en los ámbitos que no lo aplican (chat). */
  instance_limit: number | null;
  instance_remaining: number | null;
}

export type AiSessionStatus = "running" | "succeeded" | "failed" | "rejected_validation";

export interface AiValidationError {
  code: string;
  message: string;
}

export interface AiSession {
  id: string;
  kind: string;
  status: AiSessionStatus;
  attempts: number;
  response_payload: Record<string, unknown> | null;
  validation_errors: AiValidationError[] | null;
}

export interface AiProposalMealItem {
  food_id: string;
  grams: number;
}

export interface AiProposalMeal {
  meal_type: MealType;
  items: AiProposalMealItem[];
}

export interface AiProposalPayload {
  diet_plan_id: string;
  day_index: number;
  meals: AiProposalMeal[];
}

export type AiProposalStatus = "pending" | "approved" | "rejected" | "expired";

export interface AiProposal {
  id: string;
  ai_session_id: string;
  scope: string;
  payload: AiProposalPayload;
  rationale: string | null;
  status: AiProposalStatus;
}

export interface SmartLogItem {
  food_id: string;
  name_es: string;
  grams: number;
  approx_quantity_text: string;
}

export interface SmartLogResult {
  items: SmartLogItem[];
  warning: string | null;
}

export interface ReceiptScanItem extends SmartLogItem {
  original_line: string;
}

export interface ReceiptScanResult {
  items: ReceiptScanItem[];
  lines_found: number;
}

export interface RecipeIngredient {
  id: string;
  food_id: string;
  name_es: string;
  grams: number;
  kcal: number;
  protein_g: number;
  fat_g: number;
  carbs_g: number;
}

export interface RecipeNutritionTotals {
  kcal: number;
  protein_g: number;
  fat_g: number;
  carbs_g: number;
}

export interface Recipe {
  id: string;
  name: string;
  internal_ean?: string | null;
  image_url?: string | null;
  servings: number;
  prep_minutes: number | null;
  instructions: string | null;
  ingredients: RecipeIngredient[];
  totals: RecipeNutritionTotals;
  totals_per_serving: RecipeNutritionTotals;
}

export interface RecipeSummary {
  id: string;
  name: string;
  servings: number;
  prep_minutes: number | null;
}

export interface RecipeImportIngredient {
  food_id: string;
  name_es: string;
  grams: number;
  approx_quantity_text: string;
  original_line: string;
}

export interface RecipeImportDraft {
  name: string;
  servings: number;
  prep_minutes: number | null;
  instructions: string | null;
  ingredients: RecipeImportIngredient[];
  unresolved_lines: string[];
}

export interface HeatmapDay {
  date: string;
  count: number;
}

export interface Achievement {
  key: string;
  title: string;
  description: string;
  earned: boolean;
  progress: number;
  target: number;
  /** Qué dibujo lleva la insignia (`components/AchievementBadge.tsx`). */
  icon: string;
  /** Lo que cuesta conseguirlo: `bronze` | `silver` | `gold`. */
  tier: string;
  /** Para agrupar la pared de insignias (racha, agua, variedad…). */
  family: string;
  earned_on: string | null;
}

export interface GamificationSummary {
  current_streak: number;
  longest_streak: number;
  heatmap: HeatmapDay[];
  achievements: Achievement[];
  /** Conseguidos justo en esta respuesta: se celebran una vez. */
  newly_earned: string[];
}

export type ChatRole = "user" | "assistant";
export type ChatSource = "text" | "voice";

export interface ChatHistoryItem {
  id: string;
  role: ChatRole;
  content: string;
  source: ChatSource;
  created_at: string;
}

// Mismo shape que AiProposalPayload (día completo de un plan existente).
export interface ChatDayChangePayload {
  diet_plan_id: string;
  day_index: number;
  meals: AiProposalMeal[];
}

export interface ChatPantryProposalItem {
  food_id: string;
  food_name: string;
  quantity_g: number;
}

export interface ChatPantryPayload {
  items: ChatPantryProposalItem[];
}

export interface ChatDayProposal {
  scope: "day";
  ai_proposal_id: string;
  payload: ChatDayChangePayload;
}

export interface ChatPantryProposal {
  scope: "pantry";
  ai_proposal_id: string;
  payload: ChatPantryPayload;
}

export type ChatProposal = ChatDayProposal | ChatPantryProposal;

export interface ChatMessageResponse {
  message: string;
  proposal: ChatProposal | null;
}

export interface ConsentStatus {
  kind: string;
  required: boolean;
  granted: boolean;
  version: string | null;
  granted_at: string | null;
  revoked_at: string | null;
}

export interface WeightPoint {
  date: string;
  weight_kg: number;
  ma7_kg: number;
}

export interface DailyIntake {
  date: string;
  kcal: number;
  protein_g: number;
  fat_g: number;
  carbs_g: number;
}

export interface ProgressSummary {
  period_days: number;
  from_date: string;
  to_date: string;
  weight: {
    points: WeightPoint[];
    start_kg: number | null;
    end_kg: number | null;
    change_kg: number | null;
    trend_kg_per_week: number | null;
  };
  intake: {
    logging_days: number;
    adherence_pct: number;
    avg_kcal: number | null;
    avg_protein_g: number | null;
    avg_fat_g: number | null;
    avg_carbs_g: number | null;
    target_kcal: number | null;
    daily: DailyIntake[];
  };
  water_avg_ml: number | null;
}

export interface TdeeEstimate {
  week_start: string;
  estimated_tdee: number;
  avg_intake_kcal: number;
  weight_trend_kg: number;
  weight_change_kg: number;
  logging_days: number;
  is_reliable: boolean;
}

export interface TdeeHistory {
  current: TdeeEstimate | null;
  source: "adaptive_tdee" | "formula";
  history: TdeeEstimate[];
}

export interface Fasting {
  id: string;
  started_at: string;
  ended_at: string | null;
  target_hours: number;
  elapsed_hours: number;
  remaining_hours: number;
  eating_window_hours: number;
  reached_target: boolean;
  warnings: string[];
}

export interface FastingStats {
  period_days: number;
  fasts: number;
  reached_target: number;
  adherence_pct: number | null;
  avg_hours: number | null;
  longest_hours: number | null;
}

export type BodyFatMethod = "navy" | "jackson3" | "jackson7" | "durnin" | "deurenberg";

export interface BodyFatResult {
  method: BodyFatMethod;
  body_fat_pct: number;
  lean_mass_kg: number | null;
  ffmi: number | null;
  bmi: number | null;
  whtr: number | null;
  warnings: string[];
}
