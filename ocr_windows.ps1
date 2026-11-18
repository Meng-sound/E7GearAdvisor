# Windows PowerShell 5.1 + Windows.Media.Ocr。只截屏，不读取游戏进程。
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
public static class ScreenDpi {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
'@
[ScreenDpi]::SetProcessDPIAware() | Out-Null
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType=WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1
function Wait-WinRT($operation, [Type] $type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($operation))
    if (-not $task.Wait(20000)) { throw 'Windows OCR operation timed out.' }
    return $task.Result
}
$engine = $null
$engines = @{}
while ($null -ne ($requestLine = [Console]::ReadLine())) {
    $bitmap = $null; $scaled = $null; $graphics = $null; $stream = $null; $software = $null
    $temporary = $null
    try {
        $request = $requestLine | ConvertFrom-Json
        if ($request.action -eq 'languages') {
            $langs = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag })
            [Console]::WriteLine((@{ok=$true; languages=$langs} | ConvertTo-Json -Compress))
            continue
        }
        $languageTag = if ($request.language) { [string]$request.language } else { 'zh-Hans-CN' }
        if (-not $engines.ContainsKey($languageTag)) {
            $language = New-Object Windows.Globalization.Language($languageTag)
            $candidate = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
            if ($null -eq $candidate -and $languageTag -ne 'zh-Hans-CN') {
                $language = New-Object Windows.Globalization.Language('zh-Hans-CN')
                $candidate = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
            }
            if ($null -eq $candidate) { throw 'Chinese OCR unavailable. Install Chinese (Simplified) language OCR in Windows Settings.' }
            $engines[$languageTag] = $candidate
        }
        $engine = $engines[$languageTag]
        if ($request.path) {
            $bitmap = New-Object System.Drawing.Bitmap([string] $request.path)
        } else {
            $r = $request.rect
            if ($r.Count -ne 4) { throw 'Capture region must have four coordinates.' }
            $w = [int]$r[2] - [int]$r[0]; $h = [int]$r[3] - [int]$r[1]
            if ($w -lt 40 -or $h -lt 40 -or $w -gt 8000 -or $h -gt 8000) { throw 'Invalid capture region.' }
            $bitmap = New-Object System.Drawing.Bitmap($w, $h)
            $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
            $graphics.CopyFromScreen([int]$r[0], [int]$r[1], 0, 0, $bitmap.Size)
            $graphics.Dispose(); $graphics = $null
        }
        if ($request.save_to) {
            $bitmap.Save([string]$request.save_to, [System.Drawing.Imaging.ImageFormat]::Png)
        }
        if ($request.capture_only) {
            [Console]::WriteLine((@{ok=$true; width=$bitmap.Width; height=$bitmap.Height} | ConvertTo-Json -Compress))
            continue
        }
        $max = [Math]::Min(2400, [Windows.Media.Ocr.OcrEngine]::MaxImageDimension)
        $factor = [Math]::Min(2.0, $max / [double][Math]::Max($bitmap.Width, $bitmap.Height))
        $sw = [int][Math]::Round($bitmap.Width * $factor)
        $sh = [int][Math]::Round($bitmap.Height * $factor)
        $scaled = New-Object System.Drawing.Bitmap($sw, $sh)
        $graphics = [System.Drawing.Graphics]::FromImage($scaled)
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.DrawImage($bitmap, 0, 0, $sw, $sh)
        $graphics.Dispose(); $graphics = $null
        $temporary = Join-Path ([System.IO.Path]::GetTempPath()) ('e7ocr-' + [Guid]::NewGuid().ToString('N') + '.png')
        $scaled.Save($temporary, [System.Drawing.Imaging.ImageFormat]::Png)
        $file = Wait-WinRT ([Windows.Storage.StorageFile]::GetFileFromPathAsync($temporary)) ([Windows.Storage.StorageFile])
        $stream = Wait-WinRT ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $decoder = Wait-WinRT ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $software = Wait-WinRT ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $result = Wait-WinRT ($engine.RecognizeAsync($software)) ([Windows.Media.Ocr.OcrResult])
        $lines = @($result.Lines | ForEach-Object {
            $line = $_
            $words = @($line.Words | ForEach-Object {
                @{text=$_.Text; x=$_.BoundingRect.X / $factor; y=$_.BoundingRect.Y / $factor;
                  w=$_.BoundingRect.Width / $factor; h=$_.BoundingRect.Height / $factor}
            })
            @{text=$line.Text; words=$words}
        })
        [Console]::WriteLine((@{ok=$true; text=$result.Text; lines=$lines; confidence=$null;
            engine='Windows.Media.Ocr'; width=$bitmap.Width; height=$bitmap.Height} | ConvertTo-Json -Depth 7 -Compress))
    } catch {
        [Console]::WriteLine((@{ok=$false; error=$_.Exception.Message} | ConvertTo-Json -Compress))
    } finally {
        if ($graphics) { $graphics.Dispose() }
        if ($software) { $software.Dispose() }
        if ($stream) { $stream.Dispose() }
        if ($scaled) { $scaled.Dispose() }
        if ($bitmap) { $bitmap.Dispose() }
        if ($temporary -and (Test-Path -LiteralPath $temporary)) { Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue }
    }
}
