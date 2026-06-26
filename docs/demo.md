# Step-by-step Demo

End-to-end walkthrough: from a cold Azure subscription to live weather data
flowing through ADF → ADLS → Azure Function → Azure SQL → Dashboard.

> **Time estimate:** ~30 min for infra provisioning, ~15 min for wiring ADF.
> **Cost estimate:** Serverless SQL + Consumption Function + ADF run ≈ < $1 for
> a short demo session. Run `terraform destroy` when finished.

---

## Prerequisites

| Tool | Minimum version | Install |
|------|-----------------|---------|
| uv | 0.4+ | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Azure CLI | 2.59+ | `brew install azure-cli` |
| Terraform | 1.7+ | `brew tap hashicorp/tap && brew install hashicorp/tap/terraform` |
| Python | 3.11+ | `uv python install 3.12` |
| Azure Functions Core Tools | 4.x | `brew trust azure/functions && brew install azure-functions-core-tools@4` |
| jq | any | `brew install jq` |
| sqlcmd | any | `brew install sqlcmd` |

---

## Step 1 — Clone and inspect

```bash
git clone https://github.com/mohammed-taha-el-ahmar/azure-data-pipeline.git
cd azure-data-pipeline
```

Key files to review before proceeding:

```
shared/ingest.py             # fetch + wrap raw record (cloud-agnostic)
shared/transform.py          # flatten raw record → warehouse row (cloud-agnostic)
functions/transform/         # Azure Function — Blob trigger → Azure SQL insert
functions/api/               # Azure Function — HTTP trigger → GET /api/latest
frontend/index.html          # live dashboard with settings panel
scripts/run_local_pipeline.py  # local pipeline runner (SQLite, no Azure needed)
data_factory/                # ADF Copy pipeline skeleton
terraform/                   # all infrastructure as code
tests/                       # smoke tests
```

---

## Step 2 — Run smoke tests locally

Verify the shared logic works without any Azure credentials:

```bash
uv sync --extra dev --extra functions
uv run pytest
```

All tests should be green. If any fail, fix them before continuing.

---

## Step 3 — Test the full pipeline locally (optional but recommended)

Before touching Azure, run the complete pipeline on your machine using SQLite
as a stand-in for Azure SQL:

```bash
uv run scripts/run_local_pipeline.py
```

Expected output:

```
─── Pipeline run ───────────────────────────────────────
  [1/4] 📡 Fetching from Open-Meteo API…
        Temperature: 21.4°C
  [2/4] 💾 Landed → .data/raw/year=2026/month=06/day=23/…
  [3/4] ⚙️  Transformed → 21.4°C, 14.2 km/h, 58%
  [4/4] 🗄️  Loaded into SQLite (1 total rows)
─── Done ───────────────────────────────────────────────
```

You can also loop continuously or just query:

```bash
uv run scripts/run_local_pipeline.py --loop 30   # re-run every 30s
uv run scripts/run_local_pipeline.py --query     # print latest rows
uv run scripts/run_local_pipeline.py --reset     # clear local data
```

---

## Step 4 — Preview the frontend in demo mode

The frontend works immediately — no API needed — using built-in demo data:

```bash
cd frontend
python -m http.server 8080
open http://localhost:8080
```

You'll see:

- A **DEMO** badge (amber) in the header
- Randomised temperature/wind/humidity metrics
- The pipeline info panel showing "Demo mode"

Later (Step 10) you'll point it at the live Azure Function to switch to
**LIVE** mode.

---

## Step 5 — Authenticate to Azure

```bash
az login
az account set --subscription "<your-subscription-name>"

# Confirm the right subscription is active
az account show --query "{name:name, id:id}" -o table
```

---

## Step 6 — Provision infrastructure with Terraform

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

Open `terraform.tfvars` and set a strong SQL admin password:

```hcl
# terraform/terraform.tfvars
sql_admin_password = "Demo@P4ssw0rd!"   # change this
```

```bash
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

Note the outputs — you'll need them in later steps:

```bash
terraform output
# Expected:
#   data_lake_account     = "multicloudpipedl"
#   data_factory_name     = "multicloudpipe-adf"
#   transform_function_app = "multicloudpipe-transform"
#   sql_server_fqdn       = "multicloudpipe-sql.database.windows.net"
#   api_base_url          = "https://multicloudpipe-transform.azurewebsites.net/api"
#   frontend_url          = "multicloudpipe-frontend.azurestaticapps.net"
#   resource_group_name   = "multicloudpipe-rg"
```

---

## Step 7 — Create the warehouse table

```bash
SQL_FQDN=$(terraform output -raw sql_server_fqdn)
SQL_PASS='ChangeMe123!'

sqlcmd -S "$SQL_FQDN" \
       -d weatherpipeline \
       -U sqladmin \
       -P "$SQL_PASS" \
       -Q "CREATE TABLE weather_observations (
             ingested_at DATETIME2,
             latitude FLOAT,
             longitude FLOAT,
             temperature_c FLOAT,
             wind_speed_kmh FLOAT,
             humidity_pct FLOAT
           );"
```

---

## Step 8 — Wire up Azure Data Factory

### 8a. Open ADF Studio

```bash
ADF_NAME=$(terraform output -raw data_factory_name)
RG=$(terraform output -raw resource_group_name)

echo "https://adfstudio.azure.com/subscriptions/$(az account show --query id -o tsv)/resourcegroups/$RG/factories/$ADF_NAME"
```

### 8b. Create the ADLS Gen2 linked service

In ADF Studio: Manage → Linked Services → New → search "Azure Data Lake
Storage Gen2":

- **Name:** `ADLSGen2`
- **Storage account:** select the account from `terraform output data_lake_account`

### 8c. Create the HTTP linked service & datasets

The pipeline references two datasets that must exist **before** the pipeline
can be imported. We use the **HTTP connector** (not the REST connector) to
avoid gzip decoding issues with the Open-Meteo API.

**HTTP linked service** — an HTTP server linked service pointing at the
Open-Meteo base URL:

```bash
az datafactory linked-service create \
  --factory-name "$ADF_NAME" \
  --resource-group "$RG" \
  --name "OpenMeteoHttp" \
  --properties '{
    "type": "HttpServer",
    "typeProperties": {
      "url": "https://api.open-meteo.com",
      "enableServerCertificateValidation": true,
      "authenticationType": "Anonymous"
    }
  }'
```

**HTTP source dataset** — points at the Open-Meteo forecast endpoint via the
`OpenMeteoHttp` linked service:

```bash
az datafactory dataset create \
  --factory-name "$ADF_NAME" \
  --resource-group "$RG" \
  --name "OpenMeteoHttpDataset" \
  --properties '{
    "type": "Json",
    "linkedServiceName": {
      "referenceName": "OpenMeteoHttp",
      "type": "LinkedServiceReference"
    },
    "typeProperties": {
      "location": {
        "type": "HttpServerLocation",
        "relativeUrl": "/v1/forecast?latitude=48.8566&longitude=2.3522&current=temperature_2m,relative_humidity_2m,wind_speed_10m"
      }
    }
  }'
```

**ADLS Gen2 sink dataset** — lands JSON files into the `raw/weather` path via
the `ADLSGen2` linked service:

```bash
az datafactory dataset create \
  --factory-name "$ADF_NAME" \
  --resource-group "$RG" \
  --name "ADLSRawDataset" \
  --properties '{
    "type": "Json",
    "linkedServiceName": {
      "referenceName": "ADLSGen2",
      "type": "LinkedServiceReference"
    },
    "typeProperties": {
      "location": {
        "type": "AzureBlobFSLocation",
        "fileSystem": "raw",
        "folderPath": "weather"
      }
    }
  }'
```

### 8d. Import the pipeline skeleton

```bash
cd ..
az datafactory pipeline create \
  --factory-name "$ADF_NAME" \
  --resource-group "$RG" \
  --name "CopyWeatherToADLS" \
  --pipeline @data_factory/pipeline_copy_to_adls.json
```

### 8e. Add a schedule trigger (optional)

```bash
az datafactory trigger create \
  --factory-name "$ADF_NAME" \
  --resource-group "$RG" \
  --name "HourlyTrigger" \
  --properties '{
    "type": "ScheduleTrigger",
    "typeProperties": {
      "recurrence": { "frequency": "Hour", "interval": 1, "startTime": "2026-06-26T00:00:00Z", "timeZone": "UTC" }
    },
    "pipelines": [{ "pipelineReference": { "referenceName": "CopyWeatherToADLS", "type": "PipelineReference" } }]
  }'


az datafactory trigger start \
  --factory-name "$ADF_NAME" \
  --resource-group "$RG" \
  --name "HourlyTrigger"
```

---

## Step 9 — Deploy the Azure Functions

Both the **transform** (Blob trigger) and **api** (HTTP trigger) functions
live in the same Function App.

### 9a. Configure storage connection

The blob trigger monitors the ADLS Gen2 account (not the function's own
storage). Add the ADLS connection string as an app setting:

```bash
FUNC_APP=$(cd terraform && terraform output -raw transform_function_app)
RG=$(cd terraform && terraform output -raw resource_group_name)
ADLS=$(cd terraform && terraform output -raw data_lake_account)

ADLS_CONN=$(az storage account show-connection-string \
  --name "$ADLS" --resource-group "$RG" --query connectionString -o tsv)

az functionapp config appsettings set \
  --name "$FUNC_APP" --resource-group "$RG" \
  --settings "DataLakeStorage=$ADLS_CONN"
```

### 9b. Package and deploy

Make sure you're in the **project root** (not `terraform/`):

```bash
cd /path/to/azure-data-pipeline

# shared/ must be bundled alongside the functions
cp -r shared functions/shared

cd functions
func azure functionapp publish "$FUNC_APP" --python --build remote
```

> **Note:** The `functions/` directory already contains `host.json`,
> `requirements.txt`, and `local.settings.json`. If any are missing,
> the `func` CLI will fail with "Unable to find project root".

### 9c. Wire up Event Grid for the blob trigger

ADLS Gen2 (hierarchical namespace) requires an **Event Grid-based blob
trigger** — classic polling doesn't work. Create a system topic and event
subscription:

```bash
ADLS_ID=$(az storage account show --name "$ADLS" --resource-group "$RG" --query id -o tsv)
ADLS_LOCATION=$(az storage account show --name "$ADLS" --resource-group "$RG" --query location -o tsv)

# Create system topic on the storage account
az eventgrid system-topic create \
  --name "${ADLS}-topic" \
  --resource-group "$RG" \
  --source "$ADLS_ID" \
  --topic-type Microsoft.Storage.StorageAccounts \
  --location "$ADLS_LOCATION"

# Get the blob extension key for the webhook endpoint
BLOB_KEY=$(az functionapp keys list \
  --name "$FUNC_APP" --resource-group "$RG" \
  --query "systemKeys.blobs_extension" -o tsv)

ENDPOINT="https://${FUNC_APP}.azurewebsites.net/runtime/webhooks/blobs?functionName=Host.Functions.transform&code=${BLOB_KEY}"

# Subscribe blob-created events to the transform function
az eventgrid system-topic event-subscription create \
  --name BlobToTransform \
  --system-topic-name "${ADLS}-topic" \
  --resource-group "$RG" \
  --endpoint "$ENDPOINT" \
  --endpoint-type webhook \
  --included-event-types Microsoft.Storage.BlobCreated \
  --subject-begins-with /blobServices/default/containers/raw/
```

### 9d. Verify the API endpoint

```bash
API_URL=$(cd terraform && terraform output -raw api_base_url)

# Should return 404 "No observations yet" until ADF runs
curl -s "$API_URL/latest" | jq .
```

---

## Step 10 — Trigger a pipeline run and verify end-to-end

```bash
# Kick off the ADF pipeline
RUN_ID=$(az datafactory pipeline create-run \
  --factory-name "$ADF_NAME" \
  --resource-group "$RG" \
  --name "CopyWeatherToADLS" \
  --query runId -o tsv)

echo "Run ID: $RUN_ID"

# Poll until Succeeded (macOS-friendly — no `watch` needed)
while true; do
  STATUS=$(az datafactory pipeline-run show \
    --factory-name "$ADF_NAME" \
    --resource-group "$RG" \
    --run-id "$RUN_ID" \
    --query status -o tsv)
  echo "$(date '+%H:%M:%S') Status: $STATUS"
  [ "$STATUS" = "Succeeded" ] || [ "$STATUS" = "Failed" ] || [ "$STATUS" = "Cancelled" ] && break
  sleep 10
done
```

### Verify raw file landed in ADLS

```bash
ADLS=$(terraform output -raw data_lake_account)

az storage blob list \
  --account-name "$ADLS" \
  --container-name raw \
  --auth-mode key \
  --output table | head -20
```

### Verify the row made it to Azure SQL

```bash
SQL_FQDN=$(cd terraform && terraform output -raw sql_server_fqdn)
SQL_PASS='ChangeMe123!'   # same value as in terraform.tfvars

sqlcmd -S "$SQL_FQDN" -d weatherpipeline -U sqladmin -P "$SQL_PASS" \
  -Q "SELECT TOP 5 * FROM weather_observations ORDER BY ingested_at DESC"
```

### Verify the API returns data

```bash
curl -s "$API_URL/latest" | jq .
```

Expected:

```json
{
  "ingested_at": "2026-06-23T14:00:00+00:00",
  "latitude": 48.8566,
  "longitude": 2.3522,
  "temperature_c": 21.4,
  "wind_speed_kmh": 14.2,
  "humidity_pct": 58
}
```

---

## Step 11 — Connect the frontend to live data

### Option A: Local frontend → cloud API

```bash
cd frontend
python -m http.server 8080
open http://localhost:8080
```

1. Click **⚙ Settings** in the header.
2. Paste the API URL: `https://<FUNC_APP>.azurewebsites.net/api/latest`
   (from `terraform output api_base_url` + `/latest`).
3. Set refresh interval (e.g. 60 seconds).
4. Click **Save & Reload**.

The badge flips from **DEMO** → **LIVE** (green), and the dashboard shows
real data from Azure SQL.

### Option B: Deploy to Azure Static Web Apps

The Terraform config already provisions `azurerm_static_web_app.frontend`.
Deploy the frontend:

```bash
# Install the SWA CLI (requires Node.js: brew install node)
npm install -g @azure/static-web-apps-cli

# Get the deployment token
RG=$(cd terraform && terraform output -raw resource_group_name)
DEPLOY_TOKEN=$(az staticwebapp secrets list \
  --name multicloudpipe-frontend \
  --resource-group "$RG" \
  --query "properties.apiKey" -o tsv)

# Deploy from the project root (not from inside frontend/)
swa deploy ./frontend --deployment-token "$DEPLOY_TOKEN" --env production
```

Then open the Static Web App URL from `terraform output frontend_url` and
configure the API URL in the Settings panel.

---

## Step 12 — Teardown

Delete the Event Grid resources created outside Terraform (Step 9c), then
destroy the infrastructure:

```bash
cd terraform
RG=$(terraform output -raw resource_group_name)
ADLS=$(terraform output -raw data_lake_account)

# Remove the manually-created Event Grid topic (blocks terraform destroy)
az eventgrid system-topic delete \
  --name "${ADLS}-topic" --resource-group "$RG" --yes

terraform destroy
```

Confirm with `yes`. All provisioned resources (resource group, ADLS, ADF,
Azure SQL, Function App, Static Web App) are removed.

Local data can be cleaned with:

```bash
uv run scripts/run_local_pipeline.py --reset
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| ADF pipeline: `RestResourceReadFailed` / decoding error | REST connector gzip issue | Already fixed — pipeline uses HTTP connector (`JsonSource`) |
| ADF pipeline: `invalid reference 'OpenMeteoApiDataset'` | Datasets don't exist yet | Create datasets (Step 8c) before the pipeline (Step 8d) |
| ADF trigger: `MissingStartTimeInScheduleTriggerDefinition` | Missing `startTime` | Include `"startTime"` in recurrence config |
| `func publish`: "Unable to find project root" | Missing `host.json` | Ensure `functions/host.json` exists |
| Blob trigger not firing | ADLS Gen2 HNS doesn't support polling | Set up Event Grid (Step 9c) |
| Transform function: `KeyError: 'payload'` | ADF writes raw JSON, not wrapped | Already fixed — function auto-wraps with `to_raw_record()` |
| `sqlcmd` panic: index out of range | Empty shell variables | Set `$SQL_FQDN` / `$SQL_PASS` in same command |
| `sqlcmd` login failed | Wrong password | Check `grep sql_admin_password terraform/terraform.tfvars` |
| `az storage blob list` permission error | No RBAC role assigned | Use `--auth-mode key` instead of `--auth-mode login` |
| `swa deploy` fails from inside `frontend/` | Path conflict | Run from project root: `swa deploy ./frontend ...` |
| `npm: command not found` | Node.js not installed | `brew install node` |
| `watch: command not found` | macOS doesn't include `watch` | Use `while` loop (already in Step 10) or `brew install watch` |
| Frontend shows **DEMO** after setting API URL | CORS blocked or wrong URL | Check browser console; verify CORS allows `*` |
| API returns `{"error":"No observations yet"}` | ADF hasn't run yet | Trigger a manual pipeline run (Step 10) |
| API returns `{"error":"SQL_CONNECTION_STRING not configured"}` | App setting missing | Re-run `terraform apply` |
| `terraform apply` error on storage account name | Name not globally unique | Change `project_name` in `terraform.tfvars` |
| `az login` MFA loop | Conditional Access policy | Use `az login --use-device-code` |
| Local pipeline network error | No internet / API down | `curl https://api.open-meteo.com/v1/forecast?latitude=48.86&longitude=2.35&current=temperature_2m` |

> For detailed explanations and fixes, see [troubleshooting.md](troubleshooting.md).
> For a CLI quick reference, see [useful-commands.md](useful-commands.md).
