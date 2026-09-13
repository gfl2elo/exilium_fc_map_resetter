# Exilium expedition resetter

Rerolls Frontier Conquest until a map matches your tile rules. On a match, it chooses **Leave For Now**, verifies Frontier Conquest, then closes EXILIUM normally.

## 1. Install from scratch

You need **64-bit Windows 10/11**, internet access, and this complete folder in a writable location. Install EXILIUM separately. Python and Tesseract do not need to be installed beforehand.

1. Extract or copy the entire `exilium-reset` folder, including `install.ps1`, the three Python files, `requirements.txt`, and `settings.json`. Do not copy another computer's `.venv` or `runs` folders.
2. Open this folder in File Explorer, right-click empty space, and choose **Open in Terminal**. Use a PowerShell tab.
3. Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

The execution-policy option applies only to this installer process; it does not change the computer's saved policy. Windows may request administrator approval for a dependency installer.

Setup automatically:

- Reuses a working 64-bit Python 3.11–3.14 installation, or installs Python 3.13 through WinGet.
- Finds Tesseract, or installs the UB Mannheim Windows build through WinGet.
- Creates this folder's `.venv` and installs `requirements.txt` without retaining a pip download cache.
- Verifies package imports and English OCR data.
- Saves the detected Tesseract path in `settings.json`, preserving map and target settings.

Wait for **Setup complete**. Setup does not start the game or automation. Rerunning it reuses existing dependencies and the local environment.

### WinGet is missing

Install or update **App Installer** from Microsoft Store, open a new terminal, then rerun setup. WinGet comes with App Installer. [Microsoft's installation guidance](https://learn.microsoft.com/en-us/windows/package-manager/winget/)

### Custom Python or Tesseract location

Pass either or both executable paths:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -PythonPath "C:\Python314\python.exe" -TesseractPath "G:\Tesseract-OCR\tesseract.exe"
```

Replace these example paths with yours. If `.venv` was copied from another computer or is broken, rename it and rerun setup to create a fresh environment.

Setup uses the exact WinGet IDs `Python.Python.3.13` and `UB-Mannheim.TesseractOCR` from the `winget` source, and accepts their package/source agreements. [WinGet install options](https://learn.microsoft.com/en-us/windows/package-manager/winget/install)

## 2. Start the automation

Open EXILIUM at **Frontier Conquest**, with **Begin Expedition** visible and no expedition in progress. Use the English UI and the same wide window proportions as the reference screenshots. Keep the game visible and unobstructed.

From a PowerShell terminal in this folder:

```powershell
.\.venv\Scripts\python.exe .\reset.py
```

Answer the prompts for map, resource-tile total, target, and early rejection. Enter keeps each default. You then have **four seconds** to switch to EXILIUM. Answers apply to this launch; edit `settings.json` to change saved defaults.

Default: **map 6, Sanctus Valley**, with **8 shovels** or **7 shovels and 1 compass**. The total-tile question is required because detection cannot prove no unseen nodes remain.

## 3. Choose your target

Supported types: `shovel`, `compass`, `radar`. Use an exact count, inclusive range, or `rest` for one type. Omitted types mean zero.

| Target input | Meaning on an eight-tile map |
| --- | --- |
| `shovel=8` | Eight shovels |
| `shovel=rest,radar=0-1` | At most one radar; everything else shovel |
| `shovel=6,compass=2` | Six shovels and two compasses |
| `shovel=8; shovel=7,compass=1` | Either exact mix |

Early rejection is on by default. For `shovel=rest,radar=0-1`, the first compass or second radar triggers abandonment immediately. Success still requires every resource tile to be read.

```powershell
# Map 7, eight shovels; skip startup questions
.\.venv\Scripts\python.exe .\reset.py --no-prompt --map 7 --accept shovel=8

# At most one radar, all other tiles shovels
.\.venv\Scripts\python.exe .\reset.py --no-prompt --map 6 --tiles 8 --accept shovel=rest,radar=0-1

# One complete attempt; read the whole map before rejecting
.\.venv\Scripts\python.exe .\reset.py --no-prompt --max-attempts 1 --no-early-reject

# Inspect an already-open, unused map without abandoning or closing it
.\.venv\Scripts\python.exe .\reset.py --inspect
```

Repeat `--accept` for alternatives. `--countdown 0` skips the countdown. Without `--no-prompt`, command-line values become the prompt defaults. Saved JSON `accept` entries remain exact mixes totaling `tiles`.

Map selections 1–7 are included; other layouts may need different totals or camera settings. Only map 6 had a complete live cycle verified during development.

## Pause, stop, and finish

- **F9:** pause/resume. Held gestures finish and release first. Once the terminal says **Paused**, you can switch apps. Leave the game state unchanged and return to EXILIUM before resuming.
- **F8:** exit, including while paused. Leaves the expedition and game open. Ctrl+C also exits.
- **Match:** choose **Leave For Now**, verify Frontier Conquest, then request a normal game shutdown. If an exit dialog prevents closing, the script reports it rather than force-killing.

`--inspect` always reads the full map and leaves it open, even on a match. Start inspection near the normal camera entry position. Unexpected screens, incomplete scans, or lost game focus while running stop the script. It never deploys units, fights, ends a turn, or tallies results.

## Counts, timing, and storage

On completion or exit, the script prints **Resets done** and **Time spent**. A reset counts after abandoning a rejected map and verifying **Begin Expedition** again. Time accumulates across these completed cycles. Setup/countdown and the matching or interrupted attempt are excluded; pauses inside completed cycles are included.

Each launch writes small JSON results and a final `summary.json` under `runs/`, including durations and local timestamps. Screenshots are processed in memory without permanent saves. Cleanup removes this script's leftover screenshots from older versions, preserving JSON records.

Run only one copy at a time. No Codex schedule is required. Restart the automation after updating the scripts.
