# Артефакты полного аудита

Каталог `output/` воспроизводит полный набор файлов завершённого job. Файлы расположены не только как иллюстрации: вместе они показывают цепочку происхождения данных от импорта до отчёта.

| Файл | Этап | Назначение |
|---|---|---|
| `estimate_normalized.json` | импорт XLSX | Нормализованные строки сметы, помещения, работы и warnings |
| `geometry.json` | Plan Vision + validation | Canonical geometry revision 2 с measurement provenance |
| `geometry_review.json` | geometry review | Структурированный источник пользовательского review |
| `geometry_corrections.json` | user correction | История изменения высоты помещений и перехода к revision 2 |
| `price_catalog.json` | MCP | Валидированный каталог из семи работ и цен |
| `mapping.json` | Mapping | Соответствия помещений, работ и MCP IDs, schema v3 |
| `quantities.json` | deterministic audit | Контрольные количества по помещениям и объекту |
| `calculation_trace.json` | deterministic audit | Формулы, inputs, raw/rounded results и trace IDs |
| `price_checks.json` | deterministic audit | Раздельные проверки единичных цен и стоимости |
| `findings.json` | deterministic audit | Findings, warnings, coverage и итоговая сводка |
| `visual_photos.json` | photo import | Список двух фото и состояние visual workflow |
| `visual_photo_analyses.json` | Photo Vision | Результаты отдельных Vision-задач по двум фотографиям |
| `visual_insights.json` | photo aggregation | 16 валидированных наблюдений по фотографиям |
| `llm_context.json` | analyst preparation | Компактный зафиксированный контекст аналитического субагента |
| `llm_insights.json` | Analyst | Четыре валидированные гипотезы со ссылками на evidence |
| `report.html` | finalization | Автономный пользовательский HTML-отчёт |
| `generated_estimate.json` | optional estimate | 31 строка контрольной сметы, provenance и skipped coverage |
| `generated_estimate.xlsx` | optional estimate | Сформированная контрольная XLSX-смета |

## Цепочка данных

```mermaid
flowchart LR
    XLSX[estimate.xlsx] --> EN[estimate_normalized.json]
    PLAN[plan.png] --> GEO[geometry.json]
    GEO --> GR[geometry_review.json]
    GR --> GC[geometry_corrections.json]
    MCP[price-mcp] --> PC[price_catalog.json]
    EN --> MAP[mapping.json]
    GEO --> MAP
    PC --> MAP
    MAP --> Q[quantities.json]
    Q --> CT[calculation_trace.json]
    PC --> PCHK[price_checks.json]
    CT --> F[findings.json]
    PCHK --> F
    PHOTOS[site-photos.zip] --> VP[visual_photos.json]
    VP --> VPA[visual_photo_analyses.json]
    VPA --> VI[visual_insights.json]
    F --> LC[llm_context.json]
    VI --> LC
    LC --> LI[llm_insights.json]
    LI --> HTML[report.html]
    GEO --> GX[generated_estimate.json/.xlsx]
    PC --> GX
```
