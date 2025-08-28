
#!/usr/bin/env python3
# Create HTTP Monitors in F5 Distributed Cloud (XC) from a CSV file.
#
# Requirements:
#   - Python 3.8+
#   - pip install requests python-dotenv  (dotenv optional if you prefer .env)
#
# CSV Columns (header row required):
#   name,url,interval,response_codes,sni_host,ignore_cert_errors,follow_redirects,response_timeout_ms,on_failure_count,aws_regions,request_headers,description,labels
#
#   - name: monitor name (string, required, must be unique in namespace)
#   - url: target URL (string, required)
#   - interval: one of 1m,5m,15m,30m  (required)
#   - response_codes: comma-separated patterns like "2**,3**"  (optional; default "2**,3**")
#   - sni_host: optional SNI host string
#   - ignore_cert_errors: true/false (default false)
#   - follow_redirects: true/false (default true)
#   - response_timeout_ms: integer milliseconds (default 10000)
#   - on_failure_count: integer (default 2)
#   - aws_regions: comma-separated AWS region codes (e.g. ap-south-1,ap-southeast-1) (required)
#   - request_headers: semicolon-separated header pairs "Key: Value; Another-Key: Value" (optional)
#   - description: free text (optional)
#   - labels: semicolon-separated key=value pairs (optional)
#
# Auth:
#   Header "Authorization: APIToken <token>"
#   Obtain token from XC Console. Pass via --api-token or env F5XC_API_TOKEN (or .env).
#
# Usage:
#   python create_http_monitors.py --tenant <tenant> --csv monitors.csv --namespace default --dry-run
#   python create_http_monitors.py --tenant <tenant> --csv monitors.csv --namespace default

import argparse
import csv
import json
import os
import sys
import urllib.parse
from typing import Dict, List, Tuple

try:
    import requests
except ImportError as e:
    print("Missing dependency: requests. Install with `pip install requests`.", file=sys.stderr)
    raise

try:
    from dotenv import load_dotenv  # optional
    load_dotenv()
except Exception:
    pass  # dotenv is optional


INTERVAL_FIELD_MAP = {
    "1m": "interval_1_min",
    "5m": "interval_5_mins",
    "15m": "interval_15_mins",
    "30m": "interval_30_mins",
}


def parse_bool(value: str, default: bool) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_int(value: str, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(str(value).strip())
    except ValueError:
        return default


def parse_headers(s: str) -> List[Dict[str, str]]:
    if not s:
        return []
    items = []
    for pair in s.split(";"):
        if not pair.strip():
            continue
        if ":" not in pair:
            items.append({"key": pair.strip(), "value": ""})
            continue
        k, v = pair.split(":", 1)
        items.append({"key": k.strip(), "value": v.strip()})
    return items


def parse_labels(s: str) -> Dict[str, str]:
    labels = {}
    if not s:
        return labels
    for pair in s.split(";"):
        if not pair.strip():
            continue
        if "=" not in pair:
            labels[pair.strip()] = ""
        else:
            k, v = pair.split("=", 1)
            labels[k.strip()] = v.strip()
    return labels


def generate_monitor_name(url: str) -> str:
    """Generate monitor name from the FQDN in the URL."""
    parsed = urllib.parse.urlparse(url)
    fqdn = parsed.hostname or "unknown"
    return fqdn.replace(".", "-").lower() + "-monitor"


def build_payload(row: Dict[str, str]) -> Tuple[Dict, List[str]]:
    errors = []
    url = row.get("url", "").strip()
    interval = row.get("interval", "").strip().lower()
    aws_regions = [r.strip() for r in (row.get("aws_regions", "")).split(",") if r.strip()]

    if not url:
        errors.append("Missing required field: url")
    if interval not in INTERVAL_FIELD_MAP:
        errors.append(f"Invalid interval '{interval}'. Allowed: {', '.join(INTERVAL_FIELD_MAP.keys())}")
    if not aws_regions:
        errors.append("Missing required field: aws_regions (comma-separated)")

    if errors:
        return {}, errors

    name = generate_monitor_name(url)
    response_codes = [c.strip() for c in (row.get("response_codes") or "2**,3**").split(",") if c.strip()]
    headers = parse_headers(row.get("request_headers", ""))
    labels = parse_labels(row.get("labels", ""))

    spec = {
        "url": url,
        INTERVAL_FIELD_MAP[interval]: {},
        "get": {},
        "request_headers": headers,
        "on_failure_count": parse_int(row.get("on_failure_count"), 2),
        "ignore_cert_errors": parse_bool(row.get("ignore_cert_errors"), False),
        "follow_redirects": parse_bool(row.get("follow_redirects"), True),
        "response_timeout": parse_int(row.get("response_timeout_ms"), 10000),
        "external_sources": [
            {
                "aws": {
                    "regions": aws_regions
                }
            }
        ],
        "source_critical_threshold": 2,
        "sni_host": (row.get("sni_host") or "").strip() or None,
        "response_codes": response_codes,
        "health_policy": {
            "dynamic_threshold_disabled": {},
            "static_max_threshold_disabled": {},
            "static_min_threshold_disabled": {}
        }
    }
    spec = {k: v for k, v in spec.items() if v is not None}

    payload = {
        "metadata": {
            "annotations": {},
            "description": (row.get("description") or f"http monitor for {url}")[:512],
            "disable": False,
            "labels": labels,
            "name": name
        },
        "spec": spec
    }
    return payload, []


def create_monitor(session: requests.Session, base_url: str, namespace: str, payload: Dict, dry_run: bool=False) -> Tuple[bool, str]:
    path = f"/api/observability/synthetic_monitor/namespaces/{namespace}/v1_http_monitors"
    url = base_url.rstrip("/") + path
    if dry_run:
        return True, f"[DRY-RUN] Would POST to {url} with payload:\n{json.dumps(payload, indent=2)}"
    resp = session.post(url, json=payload, timeout=30)
    if resp.status_code in (200, 201, 202):
        return True, f"Created: {payload['metadata']['name']} (HTTP {resp.status_code})"
    else:
        try:
            details = resp.json()
            detail_str = json.dumps(details, indent=2)
        except Exception:
            detail_str = resp.text
        return False, f"FAILED: {payload['metadata']['name']} (HTTP {resp.status_code})\n{detail_str}"


def main():
    parser = argparse.ArgumentParser(description="Create F5 XC HTTP monitors from CSV")
    parser.add_argument("--tenant", required=True, help="Your tenant subdomain (e.g., acme if URL is https://acme.console.ves.volterra.io)")
    parser.add_argument("--csv", required=True, help="Path to CSV file with monitor definitions (no name column needed)")
    parser.add_argument("--namespace", default="default", help="XC namespace to create monitors in (default: default)")
    parser.add_argument("--api-token", default=os.getenv("F5XC_API_TOKEN"), help="XC API token, or set env F5XC_API_TOKEN")
    parser.add_argument("--base-domain", default="console.ves.volterra.io", help="XC console domain (default: console.ves.volterra.io)")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification (not recommended)")
    parser.add_argument("--dry-run", action="store_true", help="Print requests without creating monitors")
    args = parser.parse_args()

    if not args.api_token:
        print("Missing API token. Pass --api-token or set env F5XC_API_TOKEN.", file=sys.stderr)
        sys.exit(2)

    base_url = f"https://{args.tenant}.{args.base_domain}"
    headers = {
        "Authorization": f"APIToken {args.api_token}",
        "Content-Type": "application/json"
    }

    verify = not args.insecure
    session = requests.Session()
    session.headers.update(headers)
    session.verify = verify

    with open(args.csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("No rows found in CSV.", file=sys.stderr)
        sys.exit(1)

    success, fail = 0, 0
    for i, row in enumerate(rows, start=1):
        payload, errors = build_payload(row)
        if errors:
            print(f"[Row {i}] Validation errors for url='{row.get('url','?')}': " + "; ".join(errors), file=sys.stderr)
            fail += 1
            continue
        ok, msg = create_monitor(session, base_url, args.namespace, payload, dry_run=args.dry_run)
        print(msg)
        if ok:
            success += 1
        else:
            fail += 1

    print(f"\nDone. Success: {success}, Failed: {fail}, Total: {len(rows)}")
    if fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
