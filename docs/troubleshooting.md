# Troubleshooting

Common issues encountered during deployment and operation, with solutions.

---

## Azure Data Factory

### Pipeline fails: `RestResourceReadFailed — Found invalid data while decoding`

**Cause:** The ADF REST connector can't handle gzip-compressed responses from
some APIs (including Open-Meteo).

**Fix:** Use the **HTTP connector** (`HttpServer` linked service + `Json`
dataset) instead of the REST connector. The pipeline in
`data_factory/pipeline_copy_to_adls.json` already uses `JsonSource` with
`HttpReadSettings`.

### Pipeline fails: `invalid reference 'OpenMeteoApiDataset'`

**Cause:** Datasets must exist before the pipeline that references them.

**Fix:** Create datasets first (Step 8c in demo.md), then import the pipeline.

### Trigger creation fails: `MissingStartTimeInScheduleTriggerDefinition`

**Cause:** `ScheduleTrigger` requires a `startTime` in the recurrence config.

**Fix:** Include `"startTime": "2026-06-26T00:00:00Z"` in the recurrence:

```json
"recurrence": {
  "frequency": "Hour",
  "interval": 1,
  "startTime": "2026-06-26T00:00:00Z",
  "timeZone": "UTC"
}
```

---

## Azure Functions

### `func azure functionapp publish` → "Unable to find project root"

**Cause:** Missing `host.json` in the `functions/` directory.

**Fix:** Ensure `functions/` contains:
- `host.json` (runtime config)
- `requirements.txt` (Python deps: `azure-functions`, `pyodbc`)
- `local.settings.json` (local dev config)

### Blob trigger never fires (ADLS Gen2 with HNS)

**Cause:** ADLS Gen2 with hierarchical namespace (HNS) enabled does **not**
support classic blob polling triggers. You must use Event Grid.

**Fix:**
1. Set `"source": "EventGrid"` in `functions/transform/function.json`
2. Create an Event Grid system topic on the storage account
3. Create an event subscription routing `BlobCreated` events to the function's
   webhook endpoint

See Step 9c in `demo.md` for full commands.

### Blob trigger fires but SQL insert fails: `KeyError: 'payload'`

**Cause:** ADF writes the raw API response directly (flat JSON), but
`transform_record()` expects the wrapped format from `ingest.py`
(`{"ingested_at": ..., "payload": {...}}`).

**Fix:** The transform function auto-wraps raw API responses:

```python
if "payload" not in raw:
    raw = to_raw_record(raw)
```

This is already handled in the current `functions/transform/__init__.py`.

### Python version mismatch warning during publish

**Cause:** Local Python (e.g. 3.14) differs from the Function App's runtime
(3.12).

**Fix:** This is a warning only. Use `--build remote` so packages are built
against the correct Python version on Azure's side:

```bash
func azure functionapp publish "$FUNC_APP" --python --build remote
```

---

## Azure SQL

### `sqlcmd` panics: `runtime error: index out of range [0] with length 0`

**Cause:** The Go-based `sqlcmd` crashes when shell variables (`$SQL_FQDN`,
`$SQL_PASS`) are empty/unset.

**Fix:** Always set variables in the same command or use inline values:

```bash
SQL_FQDN=$(cd terraform && terraform output -raw sql_server_fqdn)
sqlcmd -S "$SQL_FQDN" -d weatherpipeline -U sqladmin -P 'YourPassword!' \
  -Q "SELECT TOP 5 * FROM weather_observations ORDER BY ingested_at DESC"
```

### Login failed for user 'sqladmin'

**Cause:** Wrong password — check `terraform.tfvars` for the actual value.

**Fix:**

```bash
grep sql_admin_password terraform/terraform.tfvars
```

Use single quotes around the password to prevent shell expansion of `!` and
other special characters.

---

## Storage (ADLS Gen2)

### `az storage blob list` → "You do not have the required permissions"

**Cause:** Your Azure AD identity doesn't have a Storage Blob Data role.

**Fix:** Use `--auth-mode key` instead of `--auth-mode login`:

```bash
az storage blob list --account-name "$ADLS" --container-name raw --auth-mode key --output table
```

---

## Static Web App / Frontend

### Frontend shows **DEMO** badge after configuring the API URL

**Cause:** CORS blocked, wrong URL, or the function isn't returning data yet.

**Fix:**
1. Open browser DevTools → Console, look for CORS errors
2. Verify the Function App has CORS set to `*` (Terraform configures this)
3. Ensure at least one pipeline run has completed (Step 10)

### `swa deploy` → "Current directory cannot be identical to artifact folder"

**Cause:** Running `swa deploy .` from inside `frontend/`.

**Fix:** Run from the project root:

```bash
swa deploy ./frontend --deployment-token "$TOKEN" --env production
```

### `npm: command not found`

**Cause:** Node.js not installed.

**Fix:** `brew install node`

---

## Terraform

### Storage account name conflict: "already taken"

**Cause:** Storage account names must be globally unique across all of Azure.

**Fix:** Change `project_name` in `terraform.tfvars` to something unique.

### Event Grid system topic: "location must match source resource"

**Cause:** The `--location` flag must match the storage account's region.

**Fix:**

```bash
ADLS_LOCATION=$(az storage account show --name "$ADLS" --resource-group "$RG" --query location -o tsv)
az eventgrid system-topic create ... --location "$ADLS_LOCATION"
```

### `terraform destroy` fails: "Resource Group still contains Resources"

**Cause:** The Event Grid system topic (created manually in Step 9c) is not
managed by Terraform, so it blocks resource group deletion.

**Fix:** Delete the topic first, then destroy:

```bash
az eventgrid system-topic delete --name "${ADLS}-topic" --resource-group "$RG" --yes
terraform destroy
```

---

## General

### `az login` MFA loop

**Fix:** Use device-code flow:

```bash
az login --use-device-code
```

### `watch: command not found` (macOS)

**Cause:** macOS doesn't ship `watch`.

**Fix:** Use a `while` loop instead (already used in demo.md), or install:

```bash
brew install watch
```

### Local pipeline fails with network error

**Fix:** Verify internet access:

```bash
curl -s "https://api.open-meteo.com/v1/forecast?latitude=48.86&longitude=2.35&current=temperature_2m" | jq .
```
