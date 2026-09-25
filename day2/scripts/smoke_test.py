"""Production smoke test - checks the API is UP *and* RIGHT (not only /health).

    python day2/scripts/smoke_test.py --url http://localhost:8090 --key <API_KEY> --expected-rate 93.72

Calls the 3 endpoints the brief requires and verifies:
  HTTP 200 · valid JSON · correct KPI values · response time < 500 ms
Exit code 0 = all checks passed, 1 = at least one failed (blocks a cutover / pipeline).
Only uses the Python standard library, so it runs anywhere (VM, GitLab CI, Jenkins).
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

PERIOD = "start_date=2026-09-01&end_date=2026-09-30"


def call(url, key=None):
    request = urllib.request.Request(url, headers={"X-API-Key": key} if key else {})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status, body, headers = response.status, response.read(), response.headers
    except urllib.error.HTTPError as error:
        status, body, headers = error.code, error.read(), error.headers
    ms = (time.perf_counter() - started) * 1000
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    return status, data, ms, headers.get("X-Live-Colour", "-")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8090")
    parser.add_argument("--key", required=True)
    parser.add_argument("--expected-rate", type=float, help="baseline settlement rate from KPI reconciliation")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    checks = []

    status, health, ms, colour = call(f"{base}/health")
    checks.append(("GET /health -> 200", status == 200, f"{status}, {ms:.0f} ms"))
    version = (health or {}).get("version", "?")

    status, summary, ms, _ = call(f"{base}/api/v1/settlement-summary?{PERIOD}", args.key)
    rate = (summary or {}).get("settlement_rate")
    checks.append(("GET /settlement-summary -> 200", status == 200, str(status)))
    checks.append(("  valid JSON with settlement_rate", rate is not None, str(rate)))
    checks.append(("  response time < 500 ms", ms < 500, f"{ms:.0f} ms"))
    checks.append(("  settlement_rate between 0 and 100", rate is not None and 0 <= rate <= 100, f"{rate} %"))
    if args.expected_rate is not None:
        checks.append(("  settlement_rate = reconciled baseline", rate == args.expected_rate,
                       f"{rate} % vs expected {args.expected_rate} %"))

    status, exceptions, ms, _ = call(f"{base}/api/v1/merchant-exceptions", args.key)
    is_list = isinstance(exceptions, list)
    checks.append(("GET /merchant-exceptions -> 200", status == 200, str(status)))
    checks.append(("  valid JSON list of merchants", is_list, f"{len(exceptions) if is_list else 0} merchants"))
    checks.append(("  every merchant rate between 0 and 100",
                   is_list and all(0 <= m["settlement_rate"] <= 100 for m in exceptions), ""))

    print(f"Smoke test {base}   version={version}   live colour={colour}   {time.strftime('%Y-%m-%d %H:%M:%S')}")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:42s} {detail}")
    passed = all(ok for _, ok, _ in checks)
    print(f"RESULT: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
