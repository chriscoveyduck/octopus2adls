# octopus2adls

Ingestion pipeline to extract smart meter consumption data from the [Octopus Energy API](https://developer.octopus.energy) and store it in Azure Data Lake Storage Gen2 (hierarchical namespace) for downstream BI / analytics (e.g. Dremio, Metabase).

## Features

- Azure Function (timer) scheduled hourly (5 min past the hour) – pulls prior hour (minus safeguard) electricity & gas consumption
- Idempotent incremental load using per-meter last interval state
- Partitioned Parquet layout optimized for query engines
- Modular Bicep infrastructure (storage, function app, observability, RBAC)
```
Octopus REST API --> Azure Function (Python Timer Trigger) --> ADLS Gen2 (consumption + curated) --> BI (Dremio/Metabase)
										|\
										| state (last interval JSON)
										v
						 Application Insights (telemetry)
```
- Extensible client (pagination, retries) prepared for future tariff & product datasets

## High-Level Architecture

Data containers (deployed):

- `consumption` (landing + enriched smart meter consumption, rates, costed data, state)
- `heating` (combined heating demand events + temperature/setpoint readings from Tado)
- `curated` (shared transformed / aggregated outputs for cross-domain analytics)

Future domain containers (not currently deployed; will be introduced when ingestion is implemented):
- `weather` (planned – external temperature & derived weather features)
																		v
													 Application Insights (telemetry)
```

## Data Model & Layout

Data containers:

- `consumption` (Octopus smart meter consumption + costed enrichment)
- `heating` (Tado radiator demand events + temperatures + target setpoints)
- `weather` (future – external temperature & weather features)
- `curated` (shared transformed / aggregated outputs)
Consumption path pattern (Parquet within the `consumption` container):

Consumption path pattern (Parquet):
State blob: `consumption/state/last_interval.json` mapping `<mpan|mprn>:<serial>` to last ingested `interval_end` (UTC ISO).

```
consumption/
	consumption/
		kind=<electricity|gas>/
			mpan_mprn=<id>/
				serial=<meter_serial>/
					date=YYYY-MM-DD/
						data.parquet
```

Columns preserved from API (`interval_start`, `interval_end`, `consumption`, plus any returned like `unit` if available). Partitioning by date yields effective pruning for range queries; further partitions (kind/mpan/serial) support meter-level filtering.

### SMETS2 Interval Considerations

SMETS2 smart meters typically supply electricity and gas consumption in half-hour intervals (30m). The ingestion logic:

1. Tracks the last ingested `interval_end` per meter.
2. On each run queries from that timestamp (exclusive) to the latest fully completed half-hour boundary.
3. De-duplicates any overlapping records (in case API returns inclusive boundary) before writing.

Units returned by the Octopus consumption endpoint are in kWh. Gas may be converted by the supplier; always validate if additional conversion factors (volume -> kWh) are needed for historical backfills.

State blob: `consumption/state/last_interval.json` mapping `<mpan|mprn>:<serial>` to last ingested `interval_end` (UTC ISO).

### Why Parquet

Columnar compression + predicate pushdown improves cost/perf for Dremio & other engines. Each daily file groups hourly (or half-hourly) intervals; typical size remains small enough for metadata efficiency while limiting tiny-file proliferation.

## Infrastructure (Bicep)

Modular templates in `infra/`:

| Module | Purpose |
| ------ | ------- |
| `storage.bicep` | ADLS Gen2 Storage Account (HNS enabled) + `consumption` & `curated` containers (locked down, no public access) |
| `function.bicep` | Consumption (Y1) or Premium plan + Function App (Python) with system-assigned managed identity & required app settings |
| `functionstorage.bicep` | Separate classic Storage Account (no HNS) for Azure Functions runtime (AzureWebJobsStorage) to isolate data lake from runtime files |
| `insights.bicep` | Application Insights component + optional Log Analytics workspace (telemetry + diagnostics sink) |
| `roleAssignments.bicep` | RBAC: grants Storage Blob Data Contributor to the Function managed identity (data-plane access) |
| `diagnostics.bicep` | Diagnostic settings routing Function & Storage logs/metrics to Log Analytics (if enabled) |
| `main.bicep` | Orchestrates modules, surfaces key outputs |

### Parameters File
An example parameters file is provided: `infra/parameters.example.json`.

Deploy (resource group scope example):

Option 1 – direct CLI:
```bash
az group create -n energy-analytics-dev -l northeurope
az deployment group create \
	-g energy-analytics-dev \
  -f infra/main.bicep \
  -p @infra/parameters.dev.json
```

Option 2 – helper script (uses infra/parameters.<env>.json):
```bash
./scripts/deploy.sh dev energy-analytics-dev
# or for prod (GRS storage etc.)
./scripts/deploy.sh prod energy-analytics-dev
```
Override location (defaults to northeurope):
```bash
./scripts/deploy.sh dev energy-analytics-dev germanywestcentral
```

Preview (what-if) before deploying (safe, no changes applied):

```bash
az deployment group what-if \
	-g energy-analytics-dev \
	-f infra/main.bicep \
	-p @infra/parameters.example.json
```

### Diagnostics
If `enableLogAnalytics` is true the deployment provisions a workspace and attaches diagnostic settings for:
- Function App: Function logs + AllMetrics
- Storage Account: Read, Write, Delete + Transaction metrics

These can power Kusto queries for operational insight and anomaly detection (e.g. missing interval trends).

### Security Notes
- No storage keys are output from templates (reduces accidental disclosure risk).
- API key for Octopus can be supplied post-deployment (recommended) or passed as parameter (secure string) – prefer secret rotation practice.
- Managed identity handles data-plane RBAC; avoid embedding connection strings beyond `AzureWebJobsStorage` requirement.

### Storage Account Separation

This deployment now provisions TWO storage accounts with distinct purposes:

1. Function runtime storage (non-HNS) – holds Azure Functions artifacts (host.json, checkpoints, scale controller leases) and is referenced only by `AzureWebJobsStorage`.
2. Data lake storage (HNS enabled) – holds analytical data (`consumption`, `curated`, rates, state) and is referenced by application logic via the `STORAGE_ACCOUNT_NAME` setting and managed identity RBAC.

Why separate them?
- Principle of least privilege: Operational runtime data is isolated from analytical data. A future rotation / reprovision of the function runtime store doesn’t risk analytics data.
- ADLS Gen2 features (hierarchical namespace, ACLs, POSIX semantics) are unnecessary for the runtime account and slightly increase cost/latency overhead if enabled unnecessarily.
- Clear blast radius: Scaling or purging the function runtime store (e.g., to clear leases) doesn’t endanger the data lake.
- Future hardening: Different network rules / private endpoints or even different replication SKUs can be applied independently.

App settings mapping:
```
AzureWebJobsStorage = connection string for <baseName>func storage account (non-HNS)
STORAGE_ACCOUNT_NAME = name of the ADLS Gen2 analytics storage account
```

Data access uses the system-assigned managed identity (role: Storage Blob Data Contributor) against the lake account only; the runtime connection string is confined to platform requirements.

### Potential Hardening (Future)
- Add Private Endpoints for Storage & Functions
- Key Vault for API key & meter config
- Defender for Cloud alerts (additional diagnostic categories)
- WAF / Front Door if HTTP triggers are later introduced

### CI
GitHub Actions workflow (`.github/workflows/ci.yml`) runs on each push/PR:
1. Install dependencies
2. Ruff lint
3. Pytest suite
4. Azure CLI install & Bicep build

Optional commented steps show how to enable a `what-if` stage with `azure/login` once `AZURE_CREDENTIALS` is configured as a secret.

Add a service principal for future automated deploys:

```bash
az ad sp create-for-rbac \
	--name octopus2adls-ci \
	--role Contributor \
	--scopes "/subscriptions/<subId>/resourceGroups/energy-analytics-dev" \
	--sdk-auth > sp.json
cat sp.json   # Put JSON into GitHub secret AZURE_CREDENTIALS
```

Then uncomment login + deploy (or what-if) steps in the workflow.

## Local Development

Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

Run tests:

```bash
pytest -q
```

### Environment Variables

Copy `.env.example` to `.env` (or configure in Azure Function App):

```
OCTOPUS_API_KEY=...          # Octopus personal API key
OCTOPUS_ACCOUNT_NUMBER=...   # Account number (A-...)
STORAGE_ACCOUNT_NAME=...     # Deployed storage account (for local use might still rely on Azure auth)
METERS_JSON=[{"kind":"electricity","mpan_or_mprn":"<mpan>","serial":"<serial>"}]
```

Add gas meter entries similarly with `kind":"gas"` and MPRN.

## Azure Function Project

Timer function defined in `functions/consumption_timer/` with schedule `0 5 * * * *` (CRON: second minute hour ...). Adjust via attribute in `__init__.py` if needed.

Logic:
1. Determine safe horizon (now UTC - 1h)
2. For each configured meter: start = last ingested interval_end (exclusive) else bootstrap last `BOOTSTRAP_LOOKBACK_DAYS` days (default 30)
3. Fetch consumption between start and horizon (paginated)
4. Write partitioned Parquet (daily) files
5. Auto-discover active tariff/product codes (if not supplied) via account agreements
6. Fetch unit rates & cost-enrich (when codes resolved)
7. Run quality checks & update state JSON

## BI Consumption Guidance

In Dremio / Metabase configure an external table/dataset pointing to `consumption/consumption`. Partition columns (`kind`, `mpan_mprn`, `serial`, `date`) become fields enabling filter pushdown. For time series: filter by `interval_start` / `interval_end`; engines will prune by `date` partition automatically if predicates align.

Suggestions for semantic layer:
- Derive `kWh` metrics (consumption already in kWh typically; validate units)
- Build daily & monthly aggregation reflections/materializations in Dremio for speed.

## Future Enhancements

- Demand & weather domain ingestion
- Key Vault integration for secret & meter config management
- Alerting/monitoring rules (missing intervals, ingestion latency, unmatched rates)
- Delta / Iceberg table format & small file compaction
- Standing charges & full bill reconciliation
- Late-arriving interval detection & reprocessing

## Historical Backfill

The timer function bootstraps the last `BOOTSTRAP_LOOKBACK_DAYS` (default 30) when no per-meter state exists. For deeper history run the standalone backfill script which iterates in configurable day chunks and respects existing state.

Example (pull 180 days in 14‑day windows with cost enrichment):
```bash
python scripts/backfill.py --days 180 --step-days 14
```

Skip cost enrichment if tariff data not yet configured:
```bash
python scripts/backfill.py --days 90 --no-cost
```

Environment variables (same as function) must be exported or in a `.env` loaded by your shell:
`OCTOPUS_API_KEY`, `OCTOPUS_ACCOUNT_NUMBER`, `STORAGE_ACCOUNT_NAME`, `METERS_JSON`, `BOOTSTRAP_LOOKBACK_DAYS` (optional), plus optional explicit tariff/product codes. If tariff/product codes are omitted the function attempts auto-discovery.

State Safety: The script will not overwrite newer intervals already captured; it only appends older data until requested history depth is covered.

## Tariffs & Cost Enrichment

If environment variables for product & tariff codes are supplied (or auto-discovered) the timer function will:

1. Fetch unit rates overlapping the ingestion window.
2. Store them under:

```
consumption/rates/kind=<electricity|gas>/product=<product_code>/tariff=<tariff_code>/date=YYYY-MM-DD/data.parquet
```

3. Join each consumption interval to the matching rate where `interval_start` ∈ [valid_from, valid_to).
4. Produce costed consumption parquet at:

```
consumption/consumption_cost/kind=.../mpan_mprn=.../serial=.../date=YYYY-MM-DD/data.parquet
```

### Tariff Resolution Order

1. Per-meter `tariff_code` override in `METERS_JSON`
2. Global env vars (`ELECTRICITY_TARIFF_CODE` / `GAS_TARIFF_CODE` and corresponding product codes)
3. Auto-discovery via account agreements (most recent active agreement at run time)

Example (explicit env vars):
```
ELECTRICITY_PRODUCT_CODE=AGILE-24-09-01
ELECTRICITY_TARIFF_CODE=E-1R-AGILE-24-09-01-A
GAS_PRODUCT_CODE=GAS-24-09-01
GAS_TARIFF_CODE=G-1R-GAS-24-09-01-A
```
Per-meter overrides: add `"tariff_code"` (and if different product, `"product_code"`) within each meter object.

Cost calculation uses `value_inc_vat` (falling back to `value_ex_vat`). Future enhancements: standing charges & tax breakdown.

## Data Quality & Completeness

The ingestion function performs lightweight quality checks:

- Interval continuity: For each batch per meter it computes expected half-hour slots covered by the first to last interval and logs a warning if any are missing.
- Rate matching: After vectorized rate join it logs the count of consumption intervals without a corresponding rate (potential tariff data gap).

Vectorized rate join uses a `searchsorted` strategy on sorted rate `valid_from` timestamps to scale efficiently for large backfills. Open-ended rates (`valid_to` null) are treated as extending forward until superseded. Intervals are matched with semantics `[valid_from, valid_to)`. Any future need for prorated splits across rate boundaries can extend the `enrich.py` utilities.

## Contributing / Extending

Add new entity ingestion by:
1. Implement API method in `octopus2adls.client`
2. Create writer method in `storage.py` (consider separate folder) with partitioning strategy
3. Extend timer or add new timer/function binding

## License

MIT
