# Blue-green cutover / rollback: send 100 % of the traffic to one colour.
#   .\switch.ps1 green     -> cutover to Version 2
#   .\switch.ps1 blue      -> rollback to Version 1
param([Parameter(Mandatory)][ValidateSet("blue", "green")][string]$Colour)

$conf = @"
# LIVE COLOUR: $Colour   (written by switch.ps1)
server {
  listen 80;
  location / {
    proxy_pass http://${Colour}:8000;
    add_header X-Live-Colour $Colour always;
  }
}
"@
Set-Content -Path "$PSScriptRoot\nginx\default.conf" -Value $conf -Encoding ascii

# Nginx checks the new config and reloads it without dropping requests.
docker compose -f "$PSScriptRoot\docker-compose.yml" exec lb nginx -s reload
if ($LASTEXITCODE -ne 0) { Write-Error "Nginx reload failed - is '$Colour' running?"; exit 1 }

$line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  100% traffic -> $Colour"
Add-Content -Path "$PSScriptRoot\..\evidence\07_blue_green_status.txt" -Value $line
Write-Host $line
