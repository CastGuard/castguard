param([string]$ProjectRoot = $PSScriptRoot, [string]$ReviewFolder = 'review')
$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $ProjectRoot).Path
$outputPath = (Resolve-Path -LiteralPath (Join-Path $rootPath $ReviewFolder)).Path
if (-not $outputPath.StartsWith($rootPath + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Review folder must be inside this project.' }
$pptxPath = Join-Path $outputPath 'CastGuard_presentation.pptx'
$pdfPath = Join-Path $outputPath 'CastGuard_presentation.pdf'
if (Test-Path -LiteralPath $pdfPath) { throw 'Existing PDF: use a new review output folder; preserve the old export.' }
$imagePath = Join-Path $outputPath 'rendered'
if (@(Get-Process POWERPNT -ErrorAction SilentlyContinue).Count -gt 0) { throw 'Existing PowerPoint session: leave it untouched; close it manually before native export.' }
New-Item -ItemType Directory -Path $imagePath -Force | Out-Null
$app = $null
$deck = $null
try {
    $app = New-Object -ComObject PowerPoint.Application
    $app.DisplayAlerts = 1
    $deck = $app.Presentations.Open($pptxPath, -1, 0, 0)
    # SaveCopyAs avoids ExportAsFixedFormat's optional PrintRange COM binding issue.
    $deck.SaveCopyAs($pdfPath, 32)
    $geometryIssues = @()
    $slideRecords = @()
    foreach ($slide in $deck.Slides) {
        $pngPath = Join-Path $imagePath ('slide-{0:D2}.png' -f $slide.SlideIndex)
        $slide.Export($pngPath, 'PNG', 1600, 900)
        $textCount = 0
        foreach ($shape in $slide.Shapes) {
            if ($shape.HasTextFrame -eq -1 -and $shape.TextFrame2.HasText -eq -1) {
                $textCount++
                $frame = $shape.TextFrame2
                $availableHeight = $shape.Height - $frame.MarginTop - $frame.MarginBottom
                if ($frame.TextRange.BoundHeight -gt ($availableHeight + 1.0)) {
                    $geometryIssues += [pscustomobject]@{slide=$slide.SlideIndex;shape=$shape.Name;text=$frame.TextRange.Text;bound_height=$frame.TextRange.BoundHeight;available_height=$availableHeight}
                }
            }
        }
        $slideRecords += [pscustomobject]@{slide=$slide.SlideIndex;png=[IO.Path]::GetFileName($pngPath);text_shapes=$textCount}
    }
    $receipt = [pscustomobject]@{exported_at=[DateTime]::UtcNow.ToString('o');renderer='Microsoft PowerPoint';application_version=$app.Version;slides=$deck.Slides.Count;pdf_bytes=(Get-Item -LiteralPath $pdfPath).Length;overflow_count=$geometryIssues.Count;overflow=$geometryIssues;slide_records=$slideRecords;exported_without_visible_window=$true}
    $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $outputPath 'checks\native_export.json') -Encoding utf8
    $receipt | Select-Object renderer,application_version,slides,pdf_bytes,overflow_count | ConvertTo-Json -Compress
} finally {
    if ($null -ne $deck) { $deck.Close(); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($deck) }
    if ($null -ne $app) { $app.Quit(); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($app) }
}
