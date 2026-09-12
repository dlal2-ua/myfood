package org.dlal2ua.myfood

import android.content.Intent
import androidx.activity.result.ActivityResult
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ActiveCaloriesBurnedRecord
import androidx.health.connect.client.records.BodyFatRecord
import androidx.health.connect.client.records.HydrationRecord
import androidx.health.connect.client.records.NutritionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.WeightRecord
import androidx.health.connect.client.records.metadata.Metadata
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import androidx.health.connect.client.units.Energy
import androidx.health.connect.client.units.Mass
import androidx.health.connect.client.units.Volume
import com.getcapacitor.JSArray
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.ActivityCallback
import com.getcapacitor.annotation.CapacitorPlugin
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.time.Instant

/**
 * Puente a Health Connect (Fase 6, sección de wearables). Health Connect
 * no tiene equivalente web — por eso esta app existe como envoltorio
 * nativo (ver `capacitor.config.ts`), aunque toda la UI real siga viviendo
 * en `apps/web` y llame a estos métodos vía `Capacitor.Plugins.HealthConnect`
 * solo cuando corre dentro de la app nativa (`Capacitor.isNativePlatform()`).
 *
 * Lectura: peso, grasa corporal, pasos, calorías activas (sección 6 —
 * el usuario elige qué entrada importar antes de que se guarde nada en
 * MyFood, igual criterio de "revisar antes de persistir" que el resto de
 * la app). Escritura: hidratación y nutrición YA registradas en MyFood, para
 * que Samsung Health/otras apps conectadas a Health Connect también las vean.
 */
@CapacitorPlugin(name = "HealthConnect")
class HealthConnectPlugin : Plugin() {

    private val scope = CoroutineScope(Dispatchers.Main)

    private val readPermissions = setOf(
        HealthPermission.getReadPermission(WeightRecord::class),
        HealthPermission.getReadPermission(BodyFatRecord::class),
        HealthPermission.getReadPermission(StepsRecord::class),
        HealthPermission.getReadPermission(ActiveCaloriesBurnedRecord::class),
    )
    private val writePermissions = setOf(
        HealthPermission.getWritePermission(HydrationRecord::class),
        HealthPermission.getWritePermission(NutritionRecord::class),
    )
    private val allPermissions = readPermissions + writePermissions

    private fun client(): HealthConnectClient = HealthConnectClient.getOrCreate(context)

    @PluginMethod
    fun checkAvailability(call: PluginCall) {
        val status = HealthConnectClient.getSdkStatus(context)
        val result = JSObject()
        result.put("available", status == HealthConnectClient.SDK_AVAILABLE)
        result.put(
            "status",
            when (status) {
                HealthConnectClient.SDK_AVAILABLE -> "available"
                HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED ->
                    "update_required"
                else -> "unavailable"
            },
        )
        call.resolve(result)
    }

    @PluginMethod
    fun checkHealthPermissions(call: PluginCall) {
        scope.launch {
            val granted = client().permissionController.getGrantedPermissions()
            val result = JSObject()
            result.put("granted", granted.containsAll(allPermissions))
            call.resolve(result)
        }
    }

    // Nombre distinto de `requestPermissions` — ese ya lo define la clase
    // base `Plugin` de Capacitor para los permisos runtime declarados vía
    // `@CapacitorPlugin(permissions = [...])`, que aquí no se usan (Health
    // Connect gestiona los suyos con su propio contrato de actividad).
    @PluginMethod
    fun requestHealthPermissions(call: PluginCall) {
        val contract = PermissionController.createRequestPermissionResultContract()
        val intent = contract.createIntent(context, allPermissions)
        startActivityForResult(call, intent, "onPermissionsResult")
    }

    @ActivityCallback
    private fun onPermissionsResult(call: PluginCall?, result: ActivityResult) {
        if (call == null) return
        val contract = PermissionController.createRequestPermissionResultContract()
        val granted = contract.parseResult(result.resultCode, result.data)
        val response = JSObject()
        response.put("granted", granted.containsAll(allPermissions))
        call.resolve(response)
    }

    @PluginMethod
    fun readRecent(call: PluginCall) {
        val days = call.getInt("days", 14) ?: 14
        val range = TimeRangeFilter.between(Instant.now().minusSeconds(days * 86400L), Instant.now())

        scope.launch {
            try {
                val weights = client()
                    .readRecords(ReadRecordsRequest(WeightRecord::class, range))
                    .records
                val bodyFat = client()
                    .readRecords(ReadRecordsRequest(BodyFatRecord::class, range))
                    .records
                val steps = client()
                    .readRecords(ReadRecordsRequest(StepsRecord::class, range))
                    .records
                val activeCalories = client()
                    .readRecords(ReadRecordsRequest(ActiveCaloriesBurnedRecord::class, range))
                    .records

                val result = JSObject()
                result.put("weights", JSArray(weights.map {
                    JSObject().apply {
                        put("time", it.time.toString())
                        put("kg", it.weight.inKilograms)
                    }
                }))
                result.put("bodyFat", JSArray(bodyFat.map {
                    JSObject().apply {
                        put("time", it.time.toString())
                        put("percentage", it.percentage.value)
                    }
                }))
                result.put(
                    "stepsTotal",
                    steps.sumOf { it.count },
                )
                result.put(
                    "activeKcalTotal",
                    activeCalories.sumOf { it.energy.inKilocalories },
                )
                call.resolve(result)
            } catch (exc: Exception) {
                call.reject("No se ha podido leer Health Connect: ${exc.message}", exc)
            }
        }
    }

    @PluginMethod
    fun writeHydration(call: PluginCall) {
        val ml = call.getDouble("ml") ?: run {
            call.reject("Falta 'ml'.")
            return
        }
        val startTime = Instant.parse(call.getString("startTime"))
        val endTime = Instant.parse(call.getString("endTime"))

        scope.launch {
            try {
                client().insertRecords(
                    listOf(
                        HydrationRecord(
                            startTime = startTime,
                            startZoneOffset = null,
                            endTime = endTime,
                            endZoneOffset = null,
                            volume = Volume.milliliters(ml),
                            metadata = Metadata.manualEntry(),
                        ),
                    ),
                )
                call.resolve()
            } catch (exc: Exception) {
                call.reject("No se ha podido escribir en Health Connect: ${exc.message}", exc)
            }
        }
    }

    @PluginMethod
    fun writeNutrition(call: PluginCall) {
        val kcal = call.getDouble("kcal") ?: run {
            call.reject("Falta 'kcal'.")
            return
        }
        val proteinG = call.getDouble("proteinG")
        val fatG = call.getDouble("fatG")
        val carbsG = call.getDouble("carbsG")
        val startTime = Instant.parse(call.getString("startTime"))
        val endTime = Instant.parse(call.getString("endTime"))

        scope.launch {
            try {
                client().insertRecords(
                    listOf(
                        NutritionRecord(
                            startTime = startTime,
                            startZoneOffset = null,
                            endTime = endTime,
                            endZoneOffset = null,
                            energy = Energy.kilocalories(kcal),
                            protein = proteinG?.let { Mass.grams(it) },
                            totalFat = fatG?.let { Mass.grams(it) },
                            totalCarbohydrate = carbsG?.let { Mass.grams(it) },
                            metadata = Metadata.manualEntry(),
                        ),
                    ),
                )
                call.resolve()
            } catch (exc: Exception) {
                call.reject("No se ha podido escribir en Health Connect: ${exc.message}", exc)
            }
        }
    }
}
