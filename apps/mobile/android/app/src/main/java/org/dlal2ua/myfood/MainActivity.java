package org.dlal2ua.myfood;

import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    private static final String PRIVACY_URL = "https://myfood.cartagena.dpdns.org/privacy";

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(HealthConnectPlugin.class);
        super.onCreate(savedInstanceState);

        // Health Connect exige mostrar por qué la app pide permisos de
        // salud antes de concederlos ("rationale") — en vez de cargar eso
        // dentro del propio WebView de Capacitor, se abre en el
        // navegador del sistema y se cierra esta instancia.
        String action = getIntent() != null ? getIntent().getAction() : null;
        if ("android.intent.action.VIEW_PERMISSION_USAGE".equals(action)
                || "androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE".equals(action)) {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(PRIVACY_URL)));
            finish();
        }
    }
}
