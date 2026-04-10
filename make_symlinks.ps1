# make_symlinks.ps1 - Create symlinks for DBs moved to E: drive (requires admin)
# Run as: Start-Process powershell -Verb RunAs -ArgumentList "-File C:\entient-worker\make_symlinks.ps1"

$links = @(
    @{ Link = 'C:\Users\Brock\.entient\v2\shapes.db';      Target = 'E:\entient\v2\shapes.db' },
    @{ Link = 'C:\Users\Brock\.entient\v2\shape_index.db'; Target = 'E:\entient\v2\shape_index.db' }
)

foreach ($l in $links) {
    if (Test-Path $l.Link) {
        Remove-Item $l.Link -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $l.Target) {
        New-Item -ItemType SymbolicLink -Path $l.Link -Target $l.Target -Force | Out-Null
        Write-Host "Linked: $($l.Link) -> $($l.Target)"
    } else {
        Write-Host "Target missing, skipping: $($l.Target)"
    }
}

Write-Host "Done."
