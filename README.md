# Azure implementation

> Part of a multi-cloud data engineering pattern — see `PORTFOLIO.md` in the
> companion repos for the cross-cloud comparison. Same `shared/` ingest +
> transform logic as `aws-data-pipeline`, `gcp-data-pipeline`, and
> `k8s-airflow-data-platform`.

`Azure Data Factory -> ADLS -> Azure Function -> Azure SQL -> Front`

## Components

- **ADLS Gen2** (`azurerm_storage_account.datalake`, container `raw`) —
  landing zone.
- **Azure Data Factory** (`azurerm_data_factory.main`) — orchestrates the
  ingest step. `data_factory/pipeline_copy_to_adls.json` is a skeleton
  Copy-activity pipeline (REST API -> ADLS) to import via the ADF
  authoring UI / `az datafactory` CLI.
- **Azure Function: transform** (`functions/transform/`) — Blob-triggered
  on `raw/`. Calls `shared.transform.transform_record` and loads the row
  into Azure SQL.
- **Azure SQL Database** (`azurerm_mssql_database.warehouse`, serverless
  tier, auto-pauses after 60 min idle) — `weather_observations` table.
- **Front end** (`frontend/index.html`) — static dashboard placeholder.

## Setup

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # edit the SQL admin password
terraform init
terraform apply
```

## TODOs to take this from scaffold to working pipeline

- [ ] In the ADF authoring UI, create:
      - a **REST linked service** pointing at the Open-Meteo API (or your
        chosen source)
      - an **ADLS Gen2 linked service** pointing at
        `azurerm_storage_account.datalake`
      - datasets `OpenMeteoApiDataset` and `ADLSRawDataset` referenced by
        `data_factory/pipeline_copy_to_adls.json`, then import that pipeline
      - a schedule trigger (hourly)
- [ ] `functions/transform/__init__.py` — implement the Azure SQL insert
      (e.g. via `pyodbc` or `pymssql`, using the
      `SQL_CONNECTION_STRING` app setting).
- [ ] Run `shared.transform.WAREHOUSE_TABLE_DDL` against the Azure SQL
      database once.
- [ ] Build a small endpoint (Azure Function HTTP trigger) that returns the
      latest row from Azure SQL as JSON, and wire it into
      `frontend/index.html`. Alternatively, embed a Power BI report built on
      the Azure SQL table.

## Teardown

```bash
cd terraform
terraform destroy
```
