# Open .docx files in Microsoft Word (hidden) and report whether Word accepts them
# (a corrupt file fails here instead of in front of a reviewer).
#   powershell -ExecutionPolicy Bypass -File tools\check_in_word.ps1 output\a.docx output\b.docx
# -ExportPdf also saves a PDF snapshot (developer use only; the product output is .docx).
param(
    [switch]$ExportPdf,
    [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)][string[]]$Paths
)

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0   # wdAlertsNone: a corrupt file raises an error instead of a dialog
$failed = 0
try {
    foreach ($p in $Paths) {
        $full = (Resolve-Path $p).Path
        try {
            # Open(FileName, ConfirmConversions, ReadOnly, AddToRecentFiles)
            $doc = $word.Documents.Open($full, $false, $true, $false)
            $pages = $doc.ComputeStatistics(2)
            $note = ""
            if ($ExportPdf) {
                $pdfPath = [System.IO.Path]::ChangeExtension($full, ".pdf")
                $doc.ExportAsFixedFormat($pdfPath, 17)   # wdExportFormatPDF
                $note = "  -> $pdfPath"
            }
            $doc.Close($false)
            Write-Output "OK      $p  ($pages page(s))$note"
        }
        catch {
            $failed++
            Write-Output "FAILED  $p  $($_.Exception.Message)"
        }
    }
}
finally {
    $word.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
}
exit $failed
