param(
    [Parameter(Mandatory=$true)]
    [string]$CurrentExe,
    [Parameter(Mandatory=$true)]
    [string]$UpdateExe
)

Write-Host "Waiting for Aegis to exit..."
Start-Sleep -Seconds 3

$retry = 0
while ($retry -lt 30) {
    try {
        Move-Item -LiteralPath $UpdateExe -Destination $CurrentExe -Force
        Write-Host "Update applied successfully."
        Start-Process -FilePath $CurrentExe
        exit 0
    } catch {
        $retry++
        Start-Sleep -Seconds 1
    }
}

Write-Host "Failed to apply update after 30 retries."
exit 1
