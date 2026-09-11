# MyFood — Producto

App web autohospedada de nutrición, dieta, suplementación e hidratación. Siete bloques:

1. Base de datos de alimentos con buscador y escáner de códigos de barras.
2. Registro diario de comidas, agua y suplementos, con macros y micronutrientes.
3. Calculadoras (TMB, gasto total, grasa corporal, objetivos de macros).
4. Generador de dietas determinista + módulo **iafood** (Claude) para dietas a medida.
5. Suplementación e hidratación con recordatorios push.
6. Progreso: peso, medidas, adherencia, tendencias y TDEE adaptativo.
7. Chat conversacional de texto y voz.

Patrón de IA "iafood": réplica del modelo de AI Coach de openGym — la IA propone estructura, el motor determinista calcula, el usuario aprueba. Ver `docs/SAFETY.md` para las reglas que gobiernan esto.

Roadmap por fases y criterios de aceptación: página de Notion "📘 MyFood (instrucciones para Claude)", sección 17.
