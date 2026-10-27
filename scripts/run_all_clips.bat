@echo off
REM ==============================================================================
REM Annotation Lab Launcher for all 15 Raw Clips
REM
REM Player Mappings:
REM   - sid_1..sid_6       -> player_id: sid
REM   - lavish_1..lavish_5 -> player_id: lavish
REM   - Mikedunn..stud2    -> player_id: mike_dunn
REM   - klay_vid           -> player_id: klay_thompson
REM
REM Split Partition (Zero split-leakage per AGENTS.md):
REM   - train: lavish, klay_thompson
REM   - val:   mike_dunn
REM   - test:  sid
REM ==============================================================================

set PYTHON=.venv\Scripts\python.exe

echo ==============================================================================
echo Select a clip to open in Annotation Lab:
echo ==============================================================================
echo [TRAIN SET - Lavish]
echo   1.  lavish_1_90deg.mp4      (clip: lavish_1, player: lavish, split: train)
echo   2.  lavish_2_90deg.mp4      (clip: lavish_2, player: lavish, split: train)
echo   3.  lavish_3_mix.mp4        (clip: lavish_3, player: lavish, split: train)
echo   4.  lavish_4_0deg.mp4       (clip: lavish_4, player: lavish, split: train)
echo   5.  lavish_5_0deg.mp4       (clip: lavish_5, player: lavish, split: train)
echo.
echo [TRAIN SET - Klay Thompson]
echo   6.  klay_vid.mp4            (clip: klay_vid, player: klay_thompson, split: train)
echo.
echo [VAL SET - Mike Dunn]
echo   7.  Mikedunn.mp4            (clip: mikedunn, player: mike_dunn, split: val)
echo   8.  mikeddunnstud1.mp4      (clip: mikedunn_stud1, player: mike_dunn, split: val)
echo   9.  mikeddunnstud2.mp4      (clip: mikedunn_stud2, player: mike_dunn, split: val)
echo.
echo [TEST SET - Sid]
echo   10. sid_1.mp4               (clip: sid_1, player: sid, split: test)
echo   11. sid_2.mp4               (clip: sid_2, player: sid, split: test)
echo   12. sid_3_mult.mp4          (clip: sid_3, player: sid, split: test)
echo   13. sid_4_97deg_wrim.mp4    (clip: sid_4, player: sid, split: test)
echo   14. sid_5_0deg.mp4          (clip: sid_5, player: sid, split: test)
echo   15. sid_6_0deg.mp4          (clip: sid_6, player: sid, split: test)
echo ==============================================================================
set /p CHOICE="Enter choice (1-15): "

if "%CHOICE%"=="1"  %PYTHON% annotation_lab.py --video raw_clips/lavish_1_90deg.mp4 --clip-id lavish_1 --player-id lavish --split train
if "%CHOICE%"=="2"  %PYTHON% annotation_lab.py --video raw_clips/lavish_2_90deg.mp4 --clip-id lavish_2 --player-id lavish --split train
if "%CHOICE%"=="3"  %PYTHON% annotation_lab.py --video raw_clips/lavish_3_mix.mp4 --clip-id lavish_3 --player-id lavish --split train
if "%CHOICE%"=="4"  %PYTHON% annotation_lab.py --video raw_clips/lavish_4_0deg.mp4 --clip-id lavish_4 --player-id lavish --split train
if "%CHOICE%"=="5"  %PYTHON% annotation_lab.py --video raw_clips/lavish_5_0deg.mp4 --clip-id lavish_5 --player-id lavish --split train
if "%CHOICE%"=="6"  %PYTHON% annotation_lab.py --video raw_clips/klay_vid.mp4 --clip-id klay_vid --player-id klay_thompson --split train
if "%CHOICE%"=="7"  %PYTHON% annotation_lab.py --video raw_clips/Mikedunn.mp4 --clip-id mikedunn --player-id mike_dunn --split val
if "%CHOICE%"=="8"  %PYTHON% annotation_lab.py --video raw_clips/mikeddunnstud1.mp4 --clip-id mikedunn_stud1 --player-id mike_dunn --split val
if "%CHOICE%"=="9"  %PYTHON% annotation_lab.py --video raw_clips/mikeddunnstud2.mp4 --clip-id mikedunn_stud2 --player-id mike_dunn --split val
if "%CHOICE%"=="10" %PYTHON% annotation_lab.py --video raw_clips/sid_1.mp4 --clip-id sid_1 --player-id sid --split test
if "%CHOICE%"=="11" %PYTHON% annotation_lab.py --video raw_clips/sid_2.mp4 --clip-id sid_2 --player-id sid --split test
if "%CHOICE%"=="12" %PYTHON% annotation_lab.py --video raw_clips/sid_3_mult.mp4 --clip-id sid_3 --player-id sid --split test
if "%CHOICE%"=="13" %PYTHON% annotation_lab.py --video raw_clips/sid_4_97deg_wrim.mp4 --clip-id sid_4 --player-id sid --split test
if "%CHOICE%"=="14" %PYTHON% annotation_lab.py --video raw_clips/sid_5_0deg.mp4 --clip-id sid_5 --player-id sid --split test
if "%CHOICE%"=="15" %PYTHON% annotation_lab.py --video raw_clips/sid_6_0deg.mp4 --clip-id sid_6 --player-id sid --split test
