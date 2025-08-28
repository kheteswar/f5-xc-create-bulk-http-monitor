
# F5 XC HTTP Monitor Creator (from CSV)

This utility reads a CSV and creates HTTP monitors in your F5 Distributed Cloud (XC) tenant using the Observability Synthetic Monitor API.

## Files
- `create_http_monitors.py` — main script
- `monitors.csv` — sample CSV you can edit

## Prerequisites
1. **Python 3.8+**
2. Install dependencies:
   ```bash
   pip install requests python-dotenv
   ```
3. **XC API Token**
   - In XC Console, create an API token with permissions to manage synthetic monitors in your namespace.
   - Export it:
     ```bash
     export F5XC_API_TOKEN='your-api-token-here'
     ```

## CSV Format
Header row is required. Columns:
```
name,url,interval,response_codes,sni_host,ignore_cert_errors,follow_redirects,response_timeout_ms,on_failure_count,aws_regions,request_headers,description,labels
```
- **name** *(required)*: unique monitor name in the namespace
- **url** *(required)*: full URL to probe
- **interval** *(required)*: one of `1m, 5m, 15m, 30m`
- **response_codes**: comma-separated codes/patterns (e.g. `2**,3**` or `200,301,302`)
- **sni_host**: optional SNI hostname
- **ignore_cert_errors**: `true`/`false` (default `false`)
- **follow_redirects**: `true`/`false` (default `true`)
- **response_timeout_ms**: integer (default `10000`)
- **on_failure_count**: integer (default `2`)
- **aws_regions** *(required)*: comma-separated AWS regions to source probes from (e.g., `ap-south-1,ap-southeast-1`)
- **request_headers**: semicolon-separated `Key: Value` pairs  
  Example: `User-Agent: XC-Monitor; Accept: */*`
- **description**: free text
- **labels**: semicolon-separated `key=value` pairs (e.g., `env=prod;team=platform`)

> Note: This script currently creates **GET** monitors (`"get": {}`). Adjust the code if you need POST/PUT with bodies.

## Run (Dry-Run First)
```bash
python3 create_http_monitors.py --tenant <your-tenant-subdomain> --namespace default --csv monitors.csv --dry-run
```
- Confirms payloads without calling the API.

## Create Monitors
```bash
python3 create_http_monitors.py --tenant <your-tenant-subdomain> --namespace default --csv monitors.csv
```
Examples:
```bash
export F5XC_API_TOKEN='xxxxx'
python create_http_monitors.py --tenant acme --csv monitors.csv
```

### Optional Flags
- `--base-domain console.ves.volterra.io` (default; override if your region uses a different console domain)
- `--insecure` (disables TLS verification; not recommended)

## How it Works
For each CSV row, the script builds a payload like:
```json
{
  "metadata": { "name": "...", "labels": {}, "description": "...", "disable": false, "annotations": {} },
  "spec": {
    "url": "...",
    "interval_5_mins": {},
    "get": {},
    "request_headers": [],
    "on_failure_count": 2,
    "ignore_cert_errors": false,
    "follow_redirects": true,
    "response_timeout": 10000,
    "external_sources": [ { "aws": { "regions": ["ap-south-1"] } } ],
    "source_critical_threshold": 2,
    "sni_host": "optional",
    "response_codes": ["2**","3**"],
    "health_policy": {
      "dynamic_threshold_disabled": {},
      "static_max_threshold_disabled": {},
      "static_min_threshold_disabled": {}
    }
  }
}
```

## Troubleshooting
- **401/403**: Check the token and its permissions in XC.
- **409**: Name already exists; pick a unique `name`.
- **400**: Validate CSV values (interval, regions, response codes).  
- To see the exact request for a row, re-run with `--dry-run` and compare.

## Extending
- Support other cloud sources (GCP/Azure) by adding to `external_sources`.
- Add upsert logic (GET existing, PATCH/PUT) if your workflow needs it.
- Accept method body and custom assertions (e.g., response text contains ...).

---

**Security Tip:** Prefer `F5XC_API_TOKEN` environment variable or a local `.env` file. Avoid committing tokens.
