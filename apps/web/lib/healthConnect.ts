import { Capacitor, registerPlugin } from "@capacitor/core";

/**
 * Puente al plugin nativo `HealthConnectPlugin.kt` (`apps/mobile`). Solo
 * existe dentro de la app Android envuelta con Capacitor — en un
 * navegador normal `Capacitor.isNativePlatform()` es `false` y ningún
 * método de aquí debería llamarse (ver `isNativeApp()`).
 */

export interface HealthConnectAvailability {
  available: boolean;
  status: "available" | "update_required" | "unavailable";
}

export interface HealthConnectPermissionResult {
  granted: boolean;
}

export interface HealthConnectWeightSample {
  time: string;
  kg: number;
}

export interface HealthConnectBodyFatSample {
  time: string;
  percentage: number;
}

export interface HealthConnectRecent {
  weights: HealthConnectWeightSample[];
  bodyFat: HealthConnectBodyFatSample[];
  stepsTotal: number;
  activeKcalTotal: number;
}

export interface WriteHydrationOptions {
  ml: number;
  startTime: string;
  endTime: string;
}

export interface WriteNutritionOptions {
  kcal: number;
  proteinG?: number;
  fatG?: number;
  carbsG?: number;
  startTime: string;
  endTime: string;
}

interface HealthConnectPluginApi {
  checkAvailability(): Promise<HealthConnectAvailability>;
  checkHealthPermissions(): Promise<HealthConnectPermissionResult>;
  requestHealthPermissions(): Promise<HealthConnectPermissionResult>;
  readRecent(options: { days?: number }): Promise<HealthConnectRecent>;
  writeHydration(options: WriteHydrationOptions): Promise<void>;
  writeNutrition(options: WriteNutritionOptions): Promise<void>;
}

export const HealthConnect = registerPlugin<HealthConnectPluginApi>("HealthConnect");

export function isNativeApp(): boolean {
  return Capacitor.isNativePlatform();
}
