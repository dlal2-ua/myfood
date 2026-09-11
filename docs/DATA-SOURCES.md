# MyFood — Fuentes de datos nutricionales

| Fuente | Licencia | Rol |
|---|---|---|
| Open Food Facts | ODbL (atribución + share-alike) | Productos de marca y códigos de barras |
| USDA FoodData Central | CC0 / dominio público | Alimentos genéricos de referencia + micronutrientes |
| CIQUAL (ANSES) | Licence Ouverte (Etalab) | Refuerzo europeo |
| BEDCA (AESAN) | Uso público | Alimentos españoles de referencia |
| FAO/INFOODS | Abierta | Códigos de nutrientes estándar |

Descartadas por comerciales: Nutritionix, Edamam, FatSecret, Spoonacular.

**Reglas:** modelo canónico por 100 g; prioridad ante conflicto USDA Foundation > USDA SR Legacy > CIQUAL > BEDCA > Open Food Facts; cada alimento guarda `source` y `license`; no depender de APIs en vivo para el catálogo (dumps nightly + Redis como fallback).

Detalle completo del ETL: Notion "📘 MyFood (instrucciones para Claude)", sección 11.
