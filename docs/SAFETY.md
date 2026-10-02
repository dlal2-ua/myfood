# MyFood — Reglas de seguridad e IA (R1-R11)

Estas reglas no se discuten ni se relajan por conveniencia. Fuente normativa: Notion "📘 MyFood (instrucciones para Claude)", sección 1.

- **R1** — La IA nunca calcula números nutricionales. Solo selecciona alimentos por ID de una lista dada. Todo número se recalcula en el backend.
- **R2** — Ningún modelo de razonamiento local en el servidor. Excepción única: Whisper autoalojado (transcripción de voz, Fase 8) — no razona, solo transcribe.
- **R3** — Multiusuario desde la primera migración: toda tabla con datos de usuario lleva `user_id NOT NULL` + FK + índice; toda consulta filtra por él.
- **R4** — Datos de salud = categoría especial RGPD art. 9: cifrado en reposo, consentimiento explícito, borrado real.
- **R5** — Nunca se envían datos identificativos al LLM. Anonimización centralizada en `ai/anonymize.py`.
- **R6** — Suelo de seguridad calórico: nunca se genera automáticamente por debajo de la TMB; inquebrantable desde la IA.
- **R7** — Disclaimers médicos visibles en onboarding, calculadoras, dietas generadas y suplementación. Fuera del registro, el usuario puede plegar cada aviso a una línea con su título (decisión del titular, 2026-10-02): plegado sigue a la vista y se despliega de un toque; nunca desaparece. En el registro va siempre entero.
- **R8** — Secretos fuera de git: `.env` en `.gitignore`, solo `.env.example` con valores ficticios.
- **R9** — Nada de datos nutricionales inventados; todo alimento sale del ETL de fuentes reales.
- **R10** — La gamificación premia el registro, nunca el déficit calórico ni el resultado corporal.
- **R11** — Row-Level Security nativa de PostgreSQL como segunda capa, además del filtrado en código.

## Excepción a R1 y R9: estimar lo que ya se ha comido

Decisión del titular (2026-10-01, Notion «Rehacer estimación de calorías del chat/audio», ampliada el 2026-10-02 al registro por foto). Al **apuntar en el diario** lo que se ha comido —por el chat, escrito o dictado, por el texto en lenguaje natural del Diario y por la foto del plato— las calorías las **estima el modelo con su conocimiento general**, plato entero y con su desglose en gramos. El catálogo deja de ser el punto de partida: con él delante, «un bocadillo de pastrami» acababa despiezado en ingredientes sueltos que no eran lo que se había comido. No hay búsqueda web: dispara los tokens de cada registro y la precisión extra no compensa en un diario de comidas.

Lo que hace que esto sea una excepción acotada y no una regla relajada:

- **Solo para registrar el pasado.** Los planes de dieta siguen exactamente igual: la IA elige alimentos por alias y los gramos los pone el optimizador (R1), con el suelo de seguridad intacto (R6).
- **Nunca se presenta como dato oficial.** Toda entrada estimada lleva `entry_source='ai_estimate'` y la web la enseña siempre con «aprox.» y la nota de que es una estimación orientativa, no una medición. Vale para ver la tendencia de semanas, no para clavar una comida.
- **Guardar un plato en el catálogo es una decisión explícita del usuario**, plato a plato, al confirmar. Entra en `foods` con `source='ai_estimate'` (fuente y licencia lo dicen), se reutiliza tal cual la siguiente vez que se nombra —sin volver a llamar al modelo— y queda fuera del motor de dietas (`PLAN_SOURCES`), que solo trabaja con dato de laboratorio o de etiqueta.
- **Se acota igual que antes**: nada por encima de 900 kcal/100 g ni de 5 kg, y nada se escribe sin que el usuario lo confirme.
- **El catálogo afina, no manda.** Cada ingrediente del desglose se contrasta con los genéricos de tablas de composición (BEDCA, CIQUAL, USDA) y, si hay uno que es el mismo alimento —se llama igual y sus kcal/100 g coinciden con las que esperaba el modelo, con un 20 % de margen—, sus valores por 100 g sustituyen a los estimados y aportan los micronutrientes (`domain/catalog_refine.py`). Los gramos son siempre los del modelo. Medido con 69 ingredientes reales: confirma 61 y la suma de calorías cambia un 0,2 %; lo que se gana son los macros de tabla y los micronutrientes, no otra cifra de calorías.
- Si el usuario nombra un producto de marca concreto, el chat lo busca y esa línea sale entera del dato real.

Disclaimer médico obligatorio: MyFood no da consejo médico ni diagnóstico. Las calculadoras y dietas son estimaciones orientativas; consultar a un profesional sanitario antes de cambios dietéticos relevantes.
