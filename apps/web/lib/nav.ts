import {
  Apple,
  BookOpen,
  Bell,
  Calculator,
  CalendarDays,
  ChefHat,
  Droplets,
  House,
  Lock,
  MessageCircle,
  MessageSquareText,
  Pill,
  Camera,
  Repeat2,
  ScanBarcode,
  Scale,
  Search,
  Settings,
  ShieldCheck,
  ShoppingCart,
  Sparkles,
  Timer,
  TrendingUp,
  User,
  Users,
  UtensilsCrossed,
  Watch,
  Refrigerator,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  /** Una línea que explica para qué sirve: es lo que hace fácil encontrar cada función. */
  description: string;
  icon: LucideIcon;
  adminOnly?: boolean;
}

export interface NavGroup {
  key: string;
  label: string;
  items: NavItem[];
}

export const HOME_ITEM: NavItem = {
  href: "/",
  label: "Hoy",
  description: "Tu día de un vistazo: calorías, macros, agua y comidas.",
  icon: House,
};

/** Todas las funciones de la app, agrupadas por lo que el usuario quiere hacer. Esta lista
 * alimenta la barra lateral (escritorio) y la pantalla «Más» (móvil), para que no haya funciones
 * que solo se encuentren en un sitio. */
export const NAV_GROUPS: NavGroup[] = [
  {
    key: "comer",
    label: "Comer",
    items: [
      { href: "/log", label: "Diario", description: "Registra y edita lo que comes cada día.", icon: BookOpen },
      { href: "/foods", label: "Alimentos", description: "Busca y filtra el catálogo por supermercado, tipo y nutrición.", icon: Apple },
      { href: "/scan", label: "Escanear", description: "Lee el código de barras de un producto.", icon: ScanBarcode },
      { href: "/recipes", label: "Recetas", description: "Tus recetas con sus macros y su código.", icon: ChefHat },
      { href: "/diet-plans", label: "Planes de dieta", description: "Menús que cuadran con tus objetivos.", icon: CalendarDays },
      { href: "/pantry", label: "Despensa", description: "Lo que tienes en casa.", icon: Refrigerator },
      { href: "/shopping-list", label: "Lista de la compra", description: "Lo que falta para tus planes.", icon: ShoppingCart },
    ],
  },
  {
    key: "seguimiento",
    label: "Seguimiento",
    items: [
      { href: "/progress", label: "Progreso", description: "Peso, tendencia y logros.", icon: TrendingUp },
      { href: "/water", label: "Agua", description: "Cuánto has bebido hoy.", icon: Droplets },
      { href: "/ayuno", label: "Ayuno", description: "Temporizador de ayuno intermitente.", icon: Timer },
      { href: "/supplements", label: "Suplementos", description: "Tomas, recordatorios y sugerencias.", icon: Pill },
      { href: "/calculadoras", label: "Calculadoras", description: "Gasto energético, grasa corporal, IMC.", icon: Calculator },
      { href: "/wearables", label: "Wearables", description: "Conecta tu reloj o pulsera.", icon: Watch },
    ],
  },
  {
    key: "asistente",
    label: "Asistente",
    items: [
      { href: "/chat", label: "Chat", description: "Pregunta sobre tu dieta y tus datos.", icon: MessageCircle },
    ],
  },
  {
    key: "cuenta",
    label: "Cuenta",
    items: [
      { href: "/profile", label: "Perfil", description: "Tus datos, objetivos y restricciones.", icon: User },
      { href: "/recordatorios", label: "Recordatorios", description: "Avisos de comidas, agua y suplementos.", icon: Bell },
      { href: "/household", label: "Hogar", description: "Comparte la compra y la despensa.", icon: Users },
      { href: "/privacy", label: "Privacidad", description: "Consentimientos, exportar y borrar tus datos.", icon: ShieldCheck },
      { href: "/security", label: "Seguridad", description: "Contraseña y verificación en dos pasos.", icon: Lock },
      { href: "/admin", label: "Administración", description: "Usuarios y ajustes del servidor.", icon: Settings, adminOnly: true },
    ],
  },
];

export type TabKey = "today" | "log" | "foods" | "more";

export interface BottomTab {
  key: TabKey;
  href: string;
  label: string;
  icon: LucideIcon;
}

/** Botones principales de la barra inferior. El botón central «+» (acciones rápidas) va entre
 * los dos primeros y los dos últimos. */
export const BOTTOM_TABS: BottomTab[] = [
  { key: "today", href: "/", label: "Hoy", icon: House },
  { key: "log", href: "/log", label: "Diario", icon: BookOpen },
  { key: "foods", href: "/foods", label: "Alimentos", icon: Apple },
  { key: "more", href: "/mas", label: "Más", icon: Sparkles },
];

export interface QuickAction {
  key: string;
  label: string;
  href?: string;
  /** Acción que no navega (p. ej. sumar un vaso de agua). */
  action?: "water";
  icon: LucideIcon;
}

export const QUICK_ACTIONS: QuickAction[] = [
  { key: "saved", label: "Lo de siempre", href: "/log#guardadas", icon: Repeat2 },
  { key: "log", label: "Registrar comida", href: "/log#registrar", icon: UtensilsCrossed },
  { key: "search", label: "Buscar alimento", href: "/foods", icon: Search },
  { key: "scan", label: "Escanear producto", href: "/scan", icon: ScanBarcode },
  { key: "water", label: "Beber un vaso", action: "water", icon: Droplets },
  { key: "photo", label: "Foto del plato", href: "/log#foto", icon: Camera },
  { key: "natural", label: "Decirlo con palabras", href: "/log#natural", icon: MessageSquareText },
  { key: "weight", label: "Registrar peso", href: "/profile#medida", icon: Scale },
  { key: "recipe", label: "Receta", href: "/recipes", icon: ChefHat },
  { key: "fasting", label: "Ayuno", href: "/ayuno", icon: Timer },
  { key: "chat", label: "Chat", href: "/chat", icon: MessageCircle },
];

export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** Qué pestaña de la barra inferior está activa: lo que no es Hoy, Diario ni Alimentos cuelga de
 * «Más», así siempre hay una pestaña marcada. */
export function tabForPath(pathname: string): TabKey {
  if (isActive(pathname, "/")) return "today";
  if (isActive(pathname, "/log")) return "log";
  if (isActive(pathname, "/foods")) return "foods";
  return "more";
}

export function visibleGroups(isAdmin: boolean): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.adminOnly || isAdmin),
  })).filter((group) => group.items.length > 0);
}

export const ACCOUNT_GROUP_KEY = "cuenta";

/** Grupos de la barra lateral: todo menos los ajustes de cuenta, que van en el menú de la cuenta
 * para que la barra quepa entera en una pantalla de portátil. */
export function sidebarGroups(isAdmin: boolean): NavGroup[] {
  return visibleGroups(isAdmin).filter((group) => group.key !== ACCOUNT_GROUP_KEY);
}

export function accountItems(isAdmin: boolean): NavItem[] {
  return visibleGroups(isAdmin).find((group) => group.key === ACCOUNT_GROUP_KEY)?.items ?? [];
}

/** Filtra las funciones por lo que escribe el usuario (etiqueta o descripción, sin acentos). */
export function filterGroups(groups: NavGroup[], query: string): NavGroup[] {
  const normalize = (s: string) =>
    s
      .toLowerCase()
      .normalize("NFD")
      .replace(/\p{M}/gu, "");
  const q = normalize(query.trim());
  if (!q) return groups;
  return groups
    .map((group) => ({
      ...group,
      items: group.items.filter(
        (item) => normalize(item.label).includes(q) || normalize(item.description).includes(q),
      ),
    }))
    .filter((group) => group.items.length > 0);
}
