# Architecture

## Generic pattern

```mermaid
flowchart LR
    A[Source API] --> B[Ingest compute]
    B --> C[(Object storage - raw)]
    C --> D[Transform compute]
    D --> E[(Data warehouse)]
    E --> F[Dashboard / front end]
```

## Azure

```mermaid
flowchart LR
    A[Open-Meteo API] -->|ADF pipeline trigger| B[ADF Copy Activity]
    B --> C[(ADLS Gen2 - raw/)]
    C -->|Blob trigger| D[Azure Function: transform]
    D --> E[(Azure SQL Database)]
    E --> F[Front end / Power BI]
```

This repo is one leg of a multi-cloud pattern — see also `aws-data-pipeline`,
`gcp-data-pipeline`, and `k8s-airflow-data-platform`. Same `shared/` ingest +
transform logic, Azure-native wiring.
