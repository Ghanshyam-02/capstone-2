# Security gate (Task 2): SAST -> Secret scan -> SCA -> Container scan.
# Run from the REPO ROOT:   .\day2\scripts\security_gate.ps1
# Reports are saved in day2\evidence\02_security_results\ (evidence).
param([string]$Image = "settlement-api:v1")

$out = "day2\evidence\02_security_results"
New-Item -ItemType Directory -Force $out | Out-Null
python -m pip install -q bandit pip-audit

Write-Host "`n=== 1. SAST (Bandit): insecure code in day1 ===" -ForegroundColor Cyan
python -m bandit -r day1 -x day1/tests,day1/.venv -f txt -o "$out\1_sast_bandit.txt"
python -m bandit -r day1 -x day1/tests,day1/.venv -lll -q          # blocks only on HIGH severity
$sast = $LASTEXITCODE

Write-Host "`n=== 2. Secret scan (Gitleaks): keys / passwords in files AND git history ===" -ForegroundColor Cyan
docker run --rm -v "${PWD}:/repo" zricethezav/gitleaks:latest detect --source /repo --redact `
    --report-path /repo/$($out -replace '\\','/')/2_secrets_gitleaks.json
$secrets = $LASTEXITCODE

Write-Host "`n=== 3. SCA (pip-audit): known vulnerabilities in our libraries ===" -ForegroundColor Cyan
python -m pip_audit -r day1\requirements.txt 2>&1 | Tee-Object "$out\3_sca_pip_audit.txt"
$sca = $LASTEXITCODE

Write-Host "`n=== 4. Container scan (Trivy): vulnerabilities in the Docker image $Image ===" -ForegroundColor Cyan
docker run --rm -v //var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest image `
    --severity HIGH,CRITICAL --no-progress $Image 2>&1 | Tee-Object "$out\4_container_trivy.txt"
docker run --rm -v //var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest image `
    --severity CRITICAL --exit-code 1 --no-progress -q $Image | Out-Null
$container = $LASTEXITCODE

$summary = @"
Security gate  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')   image=$Image
  SAST (Bandit, HIGH severity)      : $(if ($sast -eq 0) {'PASS'} else {'FAIL'})
  Secret scan (Gitleaks)            : $(if ($secrets -eq 0) {'PASS - no secrets found'} else {'FAIL - secrets found'})
  SCA (pip-audit)                   : $(if ($sca -eq 0) {'PASS - no known vulnerabilities'} else {'REVIEW - see 3_sca_pip_audit.txt'})
  Container scan (Trivy, CRITICAL)  : $(if ($container -eq 0) {'PASS - 0 critical'} else {'FAIL - critical found'})
"@
$summary | Tee-Object "$out\0_summary.txt"
