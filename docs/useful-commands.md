# Useful Commands

Quick reference for common operations during development and deployment.

---

## Local Development

```bash
# Install all dependencies
uv sync --extra dev --extra functions

# Run smoke tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=shared --cov-report=term-missing

# Run live API tests (hits Open-Meteo — needs internet)
RUN_LIVE_TESTS=1 uv run pytest

# Lint
uv run ruff check .
uv run ruff format --check .

# Auto-fix lint issues
uv run ruff check --fix .
uv run ruff format .

# Local pipeline
uv run scripts/run_local_pipeline.py              # single run
uv run scripts/run_local_pipeline.py --loop 30    # every 30s
uv run scripts/run_local_pipeline.py --query      # show data
uv run scripts/run_local_pipeline.py -n 20        # show 20 rows
uv run scripts/run_local_pipeline.py --reset      # delete local data

# Serve frontend locally
cd frontend && python -m http.server 8080
```

---

## Terraform

```bash
cd terraform

# Init / plan / apply
terraform init
terraform plan -out=tfplan
terraform apply tfplan

# Show all outputs
terraform output

# Get a specific output
terraform output -raw data_lake_account
terraform output -raw data_factory_name
terraform output -raw transform_function_app
terraform output -raw sql_server_fqdn
terraform output -raw api_base_url
terraform output -raw frontend_url
terraform output -raw resource_group_name

# Destroy everything
terraform destroy

# Format check
terraform fmt -check -recursive
terraform validate
```

---

## Azure CLI — Data Factory

```bash
# Set variables (run from terraform/ directory)
ADF_NAME=$(terraform output -raw data_factory_name)
RG=$(terraform output -raw resource_group_name)

# List pipelines
az datafactory pipeline list --factory-name "$ADF_NAME" --resource-group "$RG" -o table

# Trigger a pipeline run
RUN_ID=$(az datafactory pipeline create-run \
  --factory-name "$ADF_NAME" --resource-group "$RG" \
  --name "CopyWeatherToADLS" --query runId -o tsv)

# Check run status
az datafactory pipeline-run show \
  --factory-name "$ADF_NAME" --resource-group "$RG" \
  --run-id "$RUN_ID" --query status -o tsv

# Poll until done (macOS-friendly)
while true; do
  STATUS=$(az datafactory pipeline-run show \
    --factory-name "$ADF_NAME" --resource-group "$RG" \
    --run-id "$RUN_ID" --query status -o tsv)
  echo "$(date '+%H:%M:%S') $STATUS"
  [ "$STATUS" = "Succeeded" ] || [ "$STATUS" = "Failed" ] && break
  sleep 10
done

# Check activity errors for a failed run
az datafactory activity-run query-by-pipeline-run \
  --factory-name "$ADF_NAME" --resource-group "$RG" \
  --run-id "$RUN_ID" \
  --last-updated-after "2026-01-01T00:00:00Z" \
  --last-updated-before "2027-01-01T00:00:00Z" \
  --query "value[].{activity:activityName,status:status,error:error.message}" -o table

# List datasets
az datafactory dataset list --factory-name "$ADF_NAME" --resource-group "$RG" -o table

# List linked services
az datafactory linked-service list --factory-name "$ADF_NAME" --resource-group "$RG" -o table

# List triggers
az datafactory trigger list --factory-name "$ADF_NAME" --resource-group "$RG" -o table

# Start / stop a trigger
az datafactory trigger start --factory-name "$ADF_NAME" --resource-group "$RG" --name "HourlyTrigger"
az datafactory trigger stop --factory-name "$ADF_NAME" --resource-group "$RG" --name "HourlyTrigger"
```

---

## Azure CLI — Storage (ADLS Gen2)

```bash
ADLS=$(terraform output -raw data_lake_account)

# List blobs in raw container
az storage blob list --account-name "$ADLS" --container-name raw --auth-mode key -o table

# Download a specific blob
az storage blob download \
  --account-name "$ADLS" --container-name raw \
  --name "weather/v1/forecastXXX" --auth-mode key \
  -f /tmp/blob.json && cat /tmp/blob.json | jq .

# Delete all blobs (reset raw container)
az storage blob delete-batch --account-name "$ADLS" --source raw --auth-mode key
```

---

## Azure CLI — Functions

```bash
FUNC_APP=$(terraform output -raw transform_function_app)
RG=$(terraform output -raw resource_group_name)

# Deploy
cd functions
cp -r ../shared ./shared
func azure functionapp publish "$FUNC_APP" --python --build remote

# List deployed functions
az functionapp function list --name "$FUNC_APP" --resource-group "$RG" -o table

# Check app settings
az functionapp config appsettings list --name "$FUNC_APP" --resource-group "$RG" -o table

# Set an app setting
az functionapp config appsettings set --name "$FUNC_APP" --resource-group "$RG" \
  --settings "KEY=value"

# Get function keys
az functionapp keys list --name "$FUNC_APP" --resource-group "$RG"

# Restart the function app
az functionapp restart --name "$FUNC_APP" --resource-group "$RG"

# Call the API endpoint
API_URL=$(terraform output -raw api_base_url)
curl -s "$API_URL/latest" | jq .
```

---

## Azure CLI — SQL

```bash
SQL_FQDN=$(terraform output -raw sql_server_fqdn)
SQL_PASS='ChangeMe123!'   # from terraform.tfvars

# Query latest rows
sqlcmd -S "$SQL_FQDN" -d weatherpipeline -U sqladmin -P "$SQL_PASS" \
  -Q "SELECT TOP 10 * FROM weather_observations ORDER BY ingested_at DESC"

# Count rows
sqlcmd -S "$SQL_FQDN" -d weatherpipeline -U sqladmin -P "$SQL_PASS" \
  -Q "SELECT COUNT(*) AS total_rows FROM weather_observations"

# Truncate table (start fresh)
sqlcmd -S "$SQL_FQDN" -d weatherpipeline -U sqladmin -P "$SQL_PASS" \
  -Q "TRUNCATE TABLE weather_observations"

# Drop and recreate table
sqlcmd -S "$SQL_FQDN" -d weatherpipeline -U sqladmin -P "$SQL_PASS" \
  -Q "DROP TABLE IF EXISTS weather_observations;
      CREATE TABLE weather_observations (
        ingested_at DATETIME2, latitude FLOAT, longitude FLOAT,
        temperature_c FLOAT, wind_speed_kmh FLOAT, humidity_pct FLOAT
      );"
```

---

## Azure CLI — Static Web App

```bash
RG=$(terraform output -raw resource_group_name)

# List static web apps
az staticwebapp list --resource-group "$RG" -o table

# Get deployment token
az staticwebapp secrets list --name multicloudpipe-frontend \
  --resource-group "$RG" --query "properties.apiKey" -o tsv

# Deploy frontend
swa deploy ./frontend --deployment-token "$TOKEN" --env production
```

---

## Azure CLI — Event Grid

```bash
RG=$(terraform output -raw resource_group_name)
ADLS=$(terraform output -raw data_lake_account)

# List system topics
az eventgrid system-topic list --resource-group "$RG" -o table

# List event subscriptions on a topic
az eventgrid system-topic event-subscription list \
  --system-topic-name "${ADLS}-topic" --resource-group "$RG" -o table

# Check delivery metrics
az eventgrid system-topic event-subscription show \
  --name BlobToTransform --system-topic-name "${ADLS}-topic" \
  --resource-group "$RG" --query "{delivered:deliveryCount,failed:deadLetterCount}"
```

---

## Debugging

```bash
# Check what's actually deployed in the function app
az functionapp show --name "$FUNC_APP" --resource-group "$RG" \
  --query "{state:state,runtime:siteConfig.linuxFxVersion}" -o table

# View resource group resources
az resource list --resource-group "$RG" -o table

# Check current subscription
az account show --query "{name:name, id:id}" -o table

# Open ADF Studio URL
echo "https://adfstudio.azure.com/subscriptions/$(az account show --query id -o tsv)/resourcegroups/$RG/factories/$ADF_NAME"
```
