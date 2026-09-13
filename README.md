# Exilium expedition resetter

vibe code disclaimer

Rerolls Frontier Conquest until a map matches your tile rules. On a match, it chooses **Leave For Now**, verifies Frontier Conquest, then closes EXILIUM normally.

## 1. Install from scratch

You need **64-bit Windows 10/11**, internet access, and Git installed. Python and Tesseract do not need to be installed beforehand.

1. Create a folder wherever you want to keep the project, then open it in File Explorer.
2. Click the address bar at the top, type `cmd`, and press **Enter**. Command Prompt opens in that folder.
3. On this repository's GitHub page, click **Code → HTTPS** and copy the clone URL.
4. Run the following commands in Command Prompt to clone the repository, enter its folder, and run the PowerShell installer.

```bat
git clone https://github.com/gfl2elo/exilium_fc_map_resetter.git exilium-reset
cd exilium-reset
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

The clone contains the scripts and settings. Setup creates a fresh `.venv`.

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

> ![starting_screen_picture](/Screenshot%202026-09-11%20223720.png)

In the same Command Prompt window, run the command below. If you closed it, open the cloned `exilium-reset` folder in File Explorer, type `cmd` in the address bar, and press **Enter** first, then do:

```powershell
.\.venv\Scripts\python.exe .\reset.py
```

Answer the prompts for map, resource-tile total, target, and early rejection. Enter keeps each default. You then have **four seconds** to switch to EXILIUM. Answers apply to this launch; edit `settings.json` to change saved defaults.

Brackets show defaults I set while testing.

### Administrator rights and focus problems

To check the running game's and script's administrator rights without clicking or changing focus:

```bat
.\.venv\Scripts\python.exe .\reset.py --diagnose
```

CMD and PowerShell both work. If the diagnostic reports `EXILIUM=True, Python=False`, the game is elevated while the script is not. Run both normally where possible: close the game and launcher, turn off unnecessary **Run this program as an administrator** settings in their Compatibility/shortcut properties, then reopen them. If the game requires elevation, use an administrator terminal for the script. The script checks for this mismatch before sending input.

If Windows does not give EXILIUM focus at startup, you have another 15 seconds to switch to it. F8 and F9 remain available during this wait. During normal operation, a brief focus loss waits up to three seconds without sending input or taking focus; a persistent mismatch stops and reports the foreground window and last input. Losing focus during a held gesture releases the mouse and stops immediately.

Clicks and scrolling verify that the cursor reached the intended point and is over EXILIUM, preventing input from landing on an overlay or taskbar. Press F9 and wait for **Paused** before switching apps; return to EXILIUM before resuming.

The map-loading delay after spending the ticket is two seconds. OCR also enlarges small labels and reports the last text it read when a screen check times out.

### Change the map-loading delay

If your map needs more time to load after clicking **Expedition**, stop the script and open `reset.py` in a text editor. Inside the `enter()` function, find these lines:

```python
    game.click((.90, .935))
    game.wait(2)
    map_ready(game)
```

Change the `2` in this `game.wait(2)` to the number of seconds you want—for example, `game.wait(5)` waits five seconds. Save the file and restart the script. This applies to every selected map and does not change the four-second startup countdown.

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

Each launch writes small JSON results and a final `summary.json` under `runs/`, including durations and local timestamps. Only the **10 newest completed run folders** are kept; older completed folders and their contents are deleted at startup and after saving a summary. Screenshots are processed in memory without permanent saves. Screenshot cleanup also removes this script's leftover screenshots from older versions.
