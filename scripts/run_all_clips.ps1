# ==============================================================================
# PowerShell Launcher for Annotation Lab (All 15 Clips)
#
# Player normalization:
#   - sid_1..sid_6       -> player_id: sid
#   - lavish_1..lavish_5 -> player_id: lavish
#   - Mikedunn..stud2    -> player_id: mike_dunn
#   - klay_vid           -> player_id: klay_thompson
#
# Split Partition (Zero split-leakage per AGENTS.md):
#   - train: lavish, klay_thompson
#   - val:   mike_dunn
#   - test:  sid
# ==============================================================================

param(
    [string]$Clip = ""
)

$clips = @(
    @{ Id="lavish_1"; Video="raw_clips/lavish_1_90deg.mp4"; Player="lavish"; Split="train" },
    @{ Id="lavish_2"; Video="raw_clips/lavish_2_90deg.mp4"; Player="lavish"; Split="train" },
    @{ Id="lavish_3"; Video="raw_clips/lavish_3_mix.mp4";   Player="lavish"; Split="train" },
    @{ Id="lavish_4"; Video="raw_clips/lavish_4_0deg.mp4";  Player="lavish"; Split="train" },
    @{ Id="lavish_5"; Video="raw_clips/lavish_5_0deg.mp4";  Player="lavish"; Split="train" },
    @{ Id="klay_vid"; Video="raw_clips/klay_vid.mp4";       Player="klay_thompson"; Split="train" },
    @{ Id="mikedunn"; Video="raw_clips/Mikedunn.mp4";       Player="mike_dunn"; Split="val" },
    @{ Id="mikedunn_stud1"; Video="raw_clips/mikeddunnstud1.mp4"; Player="mike_dunn"; Split="val" },
    @{ Id="mikedunn_stud2"; Video="raw_clips/mikeddunnstud2.mp4"; Player="mike_dunn"; Split="val" },
    @{ Id="sid_1";    Video="raw_clips/sid_1.mp4";          Player="sid"; Split="test" },
    @{ Id="sid_2";    Video="raw_clips/sid_2.mp4";          Player="sid"; Split="test" },
    @{ Id="sid_3";    Video="raw_clips/sid_3_mult.mp4";     Player="sid"; Split="test" },
    @{ Id="sid_4";    Video="raw_clips/sid_4_97deg_wrim.mp4"; Player="sid"; Split="test" },
    @{ Id="sid_5";    Video="raw_clips/sid_5_0deg.mp4";     Player="sid"; Split="test" },
    @{ Id="sid_6";    Video="raw_clips/sid_6_0deg.mp4";     Player="sid"; Split="test" }
)

if ($Clip -ne "") {
    $matched = $clips | Where-Object { $_.Id -eq $Clip -or $_.Video -like "*$Clip*" }
    if ($matched) {
        & .venv\Scripts\python.exe annotation_lab.py --video $matched[0].Video --clip-id $matched[0].Id --player-id $matched[0].Player --split $matched[0].Split
        exit
    }
}

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "Select a clip to open in Annotation Lab:" -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan
for ($i = 0; $i -lt $clips.Count; $i++) {
    $c = $clips[$i]
    $color = if ($c.Split -eq "train") { "Green" } elseif ($c.Split -eq "val") { "Yellow" } else { "Magenta" }
    Write-Host (" [{0,2}] {1,-28} (player: {2,-14} | split: {3})" -f ($i + 1), $c.Video, $c.Player, $c.Split) -ForegroundColor $color
}
Write-Host "==============================================================================" -ForegroundColor Cyan

$selection = Read-Host "Enter number (1-15) or clip ID"
if ($selection -match '^\d+$') {
    $idx = [int]$selection - 1
    if ($idx -ge 0 -and $idx -lt $clips.Count) {
        $sel = $clips[$idx]
        & .venv\Scripts\python.exe annotation_lab.py --video $sel.Video --clip-id $sel.Id --player-id $sel.Player --split $sel.Split
    }
}
