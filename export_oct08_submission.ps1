$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$pptxPath = Join-Path $rootPath 'reports\oct08_submission\candidate\CastGuard_presentation.pptx'
$pdfPath = Join-Path $rootPath 'reports\oct08_submission\candidate\CastGuard_presentation.pdf'
$imagePath = Join-Path $rootPath 'reports\oct08_submission\slides'
if (@(Get-Process POWERPNT -ErrorAction SilentlyContinue).Count -gt 0) { throw 'Existing PowerPoint session; preserve it.' }
New-Item -ItemType Directory -Path $imagePath -Force | Out-Null
$app = $null
$deck = $null
try {
    $app = New-Object -ComObject PowerPoint.Application
    $app.DisplayAlerts = 1
    $deck = $app.Presentations.Open($pptxPath, -1, 0, 0)
    $deck.SaveCopyAs($pdfPath, 32)
    $issues = @()
    foreach ($slide in $deck.Slides) {
        $slide.Export((Join-Path $imagePath ('slide-{0:D2}.png' -f $slide.SlideIndex)), 'PNG', 1600, 900)
        foreach ($shape in $slide.Shapes) {
            if ($shape.HasTextFrame -eq -1 -and $shape.TextFrame2.HasText -eq -1) {
                $frame = $shape.TextFrame2
                if ($frame.TextRange.BoundHeight -gt ($shape.Height - $frame.MarginTop - $frame.MarginBottom + 1)) {
                    $issues += [pscustomobject]@{slide=$slide.SlideIndex;text=$frame.TextRange.Text;bound=$frame.TextRange.BoundHeight;height=$shape.Height}
                }
            }
        }
    }
    [pscustomobject]@{renderer='Microsoft PowerPoint';version=$app.Version;slides=$deck.Slides.Count;overflow_count=$issues.Count;overflow=$issues;exported_at=[DateTime]::UtcNow.ToString('o');hidden_export=$true} | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $imagePath 'render_receipt.json') -Encoding utf8
    Write-Output ('Exported {0} slides; text overflow {1}' -f $deck.Slides.Count,$issues.Count)
} finally {
    if ($null -ne $deck) { $deck.Close(); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($deck) }
    if ($null -ne $app) { $app.Quit(); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($app) }
}
