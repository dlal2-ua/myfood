# MyFood — Reglas de seguridad e IA (R1-R11)

Estas reglas no se discuten ni se relajan por conveniencia. Fuente normativa: Notion "📘 MyFood (instrucciones para Claude)", sección 1.

- **R1** — La IA nunca calcula números nutricionales. Solo selecciona alimentos por ID de una lista dada. Todo número se recalcula en el backend.
- **R2** — Ningún modelo de razonamiento local en el servidor. Excepción única: Whisper autoalojado (transcripción de voz, Fase 8) — no razona, solo transcribe.
- **R3** — Multiusuario desde la primera migración: toda tabla con datos de usuario lleva `user_id NOT NULL` + FK + índice; toda consulta filtra por él.
- **R4** — Datos de salud = categoría especial RGPD art. 9: cifrado en reposo, consentimiento explícito, borrado real.
- **R5** — Nunca se envían datos identificativos al LLM. Anonimización centralizada en `ai/anonymize.py`.
- **R6** — Suelo de seguridad calórico: nunca se genera automáticamente por debajo de la TMB; inquebrantable desde la IA.
- **R7** — Disclaimers médicos visibles en onboarding, calculadoras, dietas generadas y suplementación.
- **R8** — Secretos fuera de git: `.env` en `.gitignore`, solo `.env.example` con valores ficticios.
- **R9** — Nada de datos nutricionales inventados; todo alimento sale del ETL de fuentes reales.
- **R10** — La gamificación premia el registro, nunca el déficit calórico ni el resultado corporal.
- **R11** — Row-Level Security nativa de PostgreSQL como segunda capa, además del filtrado en código.

Disclaimer médico obligatorio: MyFood no da consejo médico ni diagnóstico. Las calculadoras y dietas son estimaciones orientativas; consultar a un profesional sanitario antes de cambios dietéticos relevantes.
