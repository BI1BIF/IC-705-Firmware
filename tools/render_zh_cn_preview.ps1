param([string]$OutputDirectory = (Join-Path $PSScriptRoot '../.analysis/zh-cn-preview'))

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationCore, WindowsBase

$fixture = Get-Content -Encoding UTF8 -Raw -LiteralPath (Join-Path $PSScriptRoot '../samples/zh-cn-display.json') | ConvertFrom-Json
$typeface = [Windows.Media.Typeface]::new('Microsoft YaHei')
$glyphs = $null
if (!$typeface.TryGetGlyphTypeface([ref]$glyphs)) { throw 'Microsoft YaHei was not resolved' }
$culture = [Globalization.CultureInfo]::GetCultureInfo('zh-CN')
$size = [Windows.Size]::new(480, 272)
$visual = [Windows.Media.DrawingVisual]::new()
$drawing = $visual.RenderOpen()
$checks = [Collections.Generic.List[object]]::new()
$codepoints = [Collections.Generic.HashSet[int]]::new()

function Brush([string]$hex) {
    [Windows.Media.SolidColorBrush]::new([Windows.Media.ColorConverter]::ConvertFromString($hex))
}

function Rectangle([int]$x, [int]$y, [int]$w, [int]$h, [string]$hex) {
    $drawing.DrawRectangle((Brush $hex), $null, [Windows.Rect]::new($x, $y, $w, $h))
}

function Missing([string]$value) {
    foreach ($ch in $value.ToCharArray()) {
        $cp = [int]$ch
        if (!$glyphs.CharacterToGlyphMap.ContainsKey($cp) -or $glyphs.CharacterToGlyphMap[$cp] -eq 0) { $cp }
    }
}

function Resolve-Text([string]$primary, [string]$fallback) {
    if (@(Missing $primary).Count) { return $fallback }
    $primary
}

function Draw-Text([string]$id, [string]$value, [int]$x, [int]$y, [int]$w, [int]$h, [int]$em, [string]$hex) {
    $absent = @(Missing $value)
    if ($absent.Count) { throw "Missing glyph in ${id}: $absent" }
    foreach ($ch in $value.ToCharArray()) { [void]$codepoints.Add([int]$ch) }
    $text = [Windows.Media.FormattedText]::new(
        $value, $culture, [Windows.FlowDirection]::LeftToRight, $typeface, $em, (Brush $hex), 1.0)
    $at = [Windows.Point]::new($x, $y + [math]::Floor(($h - $text.Height) / 2))
    $box = [Windows.Rect]::new($x, $y, $w, $h)
    if ($text.WidthIncludingTrailingWhitespace -gt $w -or $text.Height -gt $h -or
        !$box.Contains($text.BuildGeometry($at).Bounds) -or
        $box.Right -gt $size.Width -or $box.Bottom -gt $size.Height) {
        throw "Text exceeded its box: $id"
    }
    $drawing.DrawText($text, $at)
    $checks.Add([pscustomobject]@{
        id = $id
        width = [math]::Round($text.WidthIncludingTrailingWhitespace, 2)
        max_width = $w
        height = [math]::Round($text.Height, 2)
        max_height = $h
    })
}

try {
    # The unassigned BMP code point is a negative control for this desktop font.
    if ((Resolve-Text ([string][char]0x0378) 'English') -cne 'English' -or
        (Resolve-Text $fixture.choices[0].label 'English') -cne $fixture.choices[0].label) {
        throw 'Glyph fallback control failed'
    }

    Rectangle 0 0 480 272 '#101822'
    Rectangle 0 0 480 44 '#1D3550'
    Draw-Text title $fixture.title 18 0 290 44 24 '#F2F7FC'
    Draw-Text badge $fixture.badge 366 0 98 44 13 '#D3E3F3'
    Draw-Text breadcrumb $fixture.breadcrumb 18 48 444 24 14 '#A7C2D8'
    for ($i = 0; $i -lt $fixture.choices.Count; $i++) {
        $choice = $fixture.choices[$i]
        $y = 78 + 42 * $i
        $fill = if ($choice.active) { '#254F77' } else { '#1C2B39' }
        Rectangle 18 $y 444 36 $fill
        Draw-Text "choice-$i" $choice.label 30 $y 288 36 20 '#F2F7FC'
        if ($choice.status) { Draw-Text "status-$i" $choice.status 365 $y 80 36 14 '#D3E3F3' }
    }
    Draw-Text fallback-note $fixture.fallback_note 18 205 444 28 15 '#D3E3F3'
    Draw-Text mixed ($fixture.mixed_format -f $fixture.frequency, $fixture.mode) 18 233 444 29 15 '#A7C2D8'
} finally {
    $drawing.Close()
}

$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$bitmap = [Windows.Media.Imaging.RenderTargetBitmap]::new(480, 272, 96, 96, [Windows.Media.PixelFormats]::Pbgra32)
$bitmap.Render($visual)
$png = [Windows.Media.Imaging.PngBitmapEncoder]::new()
$png.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
$file = [IO.File]::Create((Join-Path (Resolve-Path $OutputDirectory).Path 'language-preview.png'))
try { $png.Save($file) } finally { $file.Dispose() }

$report = [pscustomobject]@{
    width = 480; height = 272
    font = $typeface.FontFamily.Source
    distinct_codepoints = $codepoints.Count
    missing_glyphs = 0
    negative_control = 'U+0378 -> English'
    text_boxes = $checks.ToArray()
}
$json = $report | ConvertTo-Json -Depth 4
$json | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $OutputDirectory 'metrics.json')
$json
