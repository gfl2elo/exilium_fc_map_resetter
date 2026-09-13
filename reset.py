"""Reroll Frontier Conquest until one configured exact tile mix is found."""
import argparse
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

import numpy as np

from desktop import Game, check_input_privileges, find_game_window
import vision

ROOT = Path(__file__).resolve().parent
TYPES = ('shovel', 'compass', 'radar')


def cleanup_summaries():
    """Keep the ten newest completed run folders, including their results."""
    root = ROOT.resolve() / 'runs'
    if not root.exists():
        return
    if root.resolve() != root:
        raise ValueError('Summary cleanup must stay inside this script\'s runs folder.')
    folders = sorted(
        (folder for folder in root.iterdir()
         if re.fullmatch(r'\d{8}-\d{6}', folder.name)
         and folder.is_dir() and folder.resolve() == folder
         and (folder / 'summary.json').is_file()),
        key=lambda folder: folder.name, reverse=True)
    for folder in folders[10:]:
        try:
            # Validate the absolute target and reject redirected descendants.
            if folder.resolve().parent != root:
                continue
            if any(path.resolve() != path for path in folder.rglob('*')):
                print(f'Skipping summary folder containing links: {folder}', file=sys.stderr)
                continue
            shutil.rmtree(folder)
        except OSError as exc:
            print(f'Could not remove old summary folder {folder}: {exc}', file=sys.stderr)


def cleanup_screenshots(folder):
    """Remove only this script's screenshot files, confined to its runs folder."""
    root = ROOT.resolve() / 'runs'
    folder = Path(folder)
    if root.resolve() != root or not folder.resolve().is_relative_to(root):
        raise ValueError('Screenshot cleanup must stay inside this script\'s runs folder.')
    folder = folder.resolve()
    pattern = re.compile(r'(?:stopped|view-\d+|tile-\d+-(?:shovel|compass|radar)|unreadable-\d+-\d+-\d+)\.png')
    removed = freed = 0
    for directory, subdirs, files in os.walk(folder, followlinks=False):
        # Never traverse junctions/symlinks to another directory.
        subdirs[:] = [name for name in subdirs
                      if (Path(directory) / name).resolve() == Path(directory) / name]
        for name in files:
            if not pattern.fullmatch(name):
                continue
            path = Path(directory) / name
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                continue
            try:
                size = path.stat().st_size
                path.unlink()
                removed += 1
                freed += size
            except FileNotFoundError:
                pass
            except OSError as exc:
                print(f'Could not remove screenshot {path}: {exc}', file=sys.stderr)
    return removed, freed


def possible(counts, mixes):
    """At least one exact target must still contain all nodes read so far."""
    return any(all(counts.get(k, 0) <= mix.get(k, 0) for k in TYPES) for mix in mixes)


def parse_mixes(expressions, total):
    """Expand counts/ranges and one optional 'rest' into exact accepted mixes."""
    mixes = []
    for expression in expressions:
        limits = dict.fromkeys(TYPES, (0, 0))
        supplied = set()
        rest = None
        for item in expression.split(','):
            key, value = (part.strip().lower() for part in item.split('='))
            if key not in TYPES or key in supplied:
                raise ValueError('Use shovel, compass and radar, at most once per mix.')
            supplied.add(key)
            if value == 'rest':
                if rest is not None:
                    raise ValueError('Only one tile type can be rest.')
                rest = key
                limits[key] = (0, total)
            else:
                if not re.fullmatch(r'\d+(?:-\d+)?', value):
                    raise ValueError('Counts must be a number, range such as 0-1, or rest.')
                numbers = list(map(int, value.split('-')))
                lo, hi = numbers[0], numbers[-1]
                if not 0 <= lo <= hi <= total:
                    raise ValueError(f'Counts must be between 0 and {total}.')
                limits[key] = (lo, hi)
        for shovel in range(limits['shovel'][0], limits['shovel'][1] + 1):
            for compass in range(limits['compass'][0], limits['compass'][1] + 1):
                radar = total - shovel - compass
                if limits['radar'][0] <= radar <= limits['radar'][1]:
                    mix = dict(zip(TYPES, (shovel, compass, radar)))
                    if mix not in mixes:
                        mixes.append(mix)
        if not any(all(limits[k][0] <= mix[k] <= limits[k][1] for k in TYPES) for mix in mixes):
            raise ValueError(f'Target cannot total {total} tiles: {expression}')
    return mixes


def prompt_settings(config):
    print('\nExilium resetter — Enter keeps the displayed value.')
    while True:
        try:
            number = int(input(f'Map number [{config["map"]}]: ') or config['map'])
            if str(number) not in config['maps']:
                raise ValueError('Choose a configured map number.')
            total = int(input(f'Resource tiles on this map [{config["tiles"]}]: ') or config['tiles'])
            if total < 1:
                raise ValueError('The total must be positive.')
            default = '; '.join(','.join(f'{k}={v}' for k, v in mix.items() if v) for mix in config['accept'])
            print('Counts: shovel=8, or shovel=rest,radar=0-1 (at most one radar; everything else shovel).')
            print('Separate alternative targets with ;. Unspecified types mean zero.')
            answer = input(f'Target [{default}]: ').strip() or default
            mixes = parse_mixes(answer.split(';'), total)
            enabled = config.get('early_reject', True)
            answer = input(f'Reject impossible maps early? [{"Y/n" if enabled else "y/N"}]: ').strip().lower()
            if answer not in ('', 'y', 'yes', 'n', 'no'):
                raise ValueError('Answer yes or no.')
            config.update(map=number, tiles=total, accept=mixes,
                          early_reject=enabled if not answer else answer in ('y', 'yes'))
            return
        except ValueError as exc:
            print(f'{exc} Please enter the settings again.\n')


def compact(value):
    return re.sub(r'[^a-z0-9]', '', value.lower())


def wait_text(game, words, box, timeout=20, psm=6):
    deadline = game.active_clock() + timeout
    recognized = ''
    while game.active_clock() < deadline:
        shot = game.capture()
        recognized = vision.text(shot, box, psm=psm)
        game.check()  # Honor F8/F9 pressed while OCR was working.
        if compact(words) in compact(recognized):
            return shot
        game.wait(.4)
    raise RuntimeError(f'Expected screen text was not found: {words!r}; last OCR: {recognized.strip()!r}')


def map_ready(game):
    shot = wait_text(game, 'Round 1/10', (.302, .03, .378, .06))
    troops = compact(vision.text(shot, (.04, .095, .062, .12), psm=7))
    if troops != '06':
        raise RuntimeError('Could not verify zero deployed units. Leave the expedition untouched.')
    return shot


def enter(game, profile):
    # The caller has verified Frontier Conquest and started the reset timer.
    game.click((.885, .945))
    game.wait(1.5)
    # Map names sit over animated scenery and are unreliable in a full-grid
    # OCR pass. Verify the picker's fixed label, then verify the selected name
    # on its detail screen before pressing Expedition.
    wait_text(game, 'Expedition Assessment Room', (.025, .90, .33, .98))
    game.click(profile['select'])
    wait_text(game, profile['name'], (.72, .015, .99, .17))
    wait_text(game, 'Expedition', (.85, .915, .945, .95))
    game.click((.90, .935))
    game.wait(2)
    map_ready(game)


def abandon(game):
    game.click((.12, .50))  # Dismiss any information card.
    map_ready(game)
    game.click((.028, .047))
    # Sparse text mode separates the heading from its tiny decorative subtitle.
    wait_text(game, 'Pause Expedition', (.32, .14, .70, .26), psm=11)
    wait_text(game, 'Abandon Expedition', (.35, .50, .45, .61))
    game.click((.404, .465))
    wait_text(game, 'Do you wish', (.29, .41, .71, .56))
    wait_text(game, 'Confirm', (.52, .66, .70, .74))
    game.click((.607, .706))
    wait_text(game, 'Begin Expedition', (.77, .89, .99, .99))


def leave_for_now(game):
    game.click((.12, .50))
    map_ready(game)
    game.click((.028, .047))
    wait_text(game, 'Pause Expedition', (.32, .14, .70, .26), psm=11)
    wait_text(game, 'Leave For Now', (.55, .50, .65, .61))
    game.click((.597, .465))
    # A saved expedition may show Continue Expedition rather than Begin.
    wait_text(game, 'Frontier Conquest', (.025, .065, .39, .20))
    game.wait(1)


def scan(game, config):
    map_ready(game)
    game.click((.12, .50))
    game.zoom_out()
    # One upward drag reaches the bottom from the freshly loaded map.
    game.drag(config['pan_end'], config['pan_start'])
    offset = np.zeros(2)
    seen = []
    for view in range(config['max_pans'] + 1):
        base = game.capture()
        for point in vision.nodes(base):
            world = np.asarray(point) - offset
            if any(np.linalg.norm(world - row['world']) < 22 for row in seen):
                continue
            # Click the exposed lower part of the node, left of its badge.
            height = base.height * 2048 / base.width
            click = ((point[0] - 20) / 2048, (point[1] - 8) / height)
            game.click((.12, .50))
            game.click(click)
            kind = None
            for _ in range(3):
                game.wait(.35)
                detail = game.capture()
                kind = vision.tile_type(detail)
                game.check()
                if kind:
                    break
            if kind:
                seen.append({'world': world, 'type': kind})
                print(f'  Tile {len(seen)}: {kind}', flush=True)
                if len(seen) > config['tiles']:
                    raise RuntimeError('Found more resource tiles than configured. Check tiles in settings.')
                counts = dict(Counter(row['type'] for row in seen))
                if config.get('early_reject', True) and not possible(counts, config['accept']):
                    print(f'  Early rejection after {len(seen)}/{config["tiles"]} tiles: no target remains possible.', flush=True)
                    return counts, True
            game.click((.12, .50))
        if len(seen) >= config['tiles']:
            if len(seen) != config['tiles']:
                raise RuntimeError('Found more resource tiles than configured. Check tiles in settings.')
            return dict(Counter(row['type'] for row in seen)), False
        if view == config['max_pans']:
            break
        before = game.capture()
        game.drag(config['pan_start'], config['pan_end'])
        after = game.capture()
        shift = vision.pan_shift(before, after)
        if abs(shift[0]) > 25 or shift[1] < 20:
            raise RuntimeError(f'Could not reveal more map with a downward drag: {shift}.')
        offset += shift
    raise RuntimeError(f'Only read {len(seen)} of {config["tiles"]} resource tiles; expedition preserved.')


def validate(config):
    if str(config['map']) not in config['maps']:
        raise ValueError('Map must have an entry in maps.')
    if not isinstance(config['tiles'], int) or config['tiles'] < 1:
        raise ValueError('tiles must be a positive integer.')
    if not config['accept']:
        raise ValueError('Provide at least one accepted tile mix.')
    if type(config.get('early_reject', True)) is not bool:
        raise ValueError('early_reject must be true or false.')
    if type(config.get('countdown_seconds', 4)) is not int or config.get('countdown_seconds', 4) < 0:
        raise ValueError('countdown_seconds must be a nonnegative integer.')
    for mix in config['accept']:
        if set(mix) - {'shovel', 'compass', 'radar'}:
            raise ValueError('Allowed tile types: shovel, compass, radar.')
        if any(type(v) is not int or v < 0 for v in mix.values()) or sum(mix.values()) != config['tiles']:
            raise ValueError('Each accepted mix must total exactly tiles; use nonnegative integer counts.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'settings.json')
    parser.add_argument('--map', type=int, help='Override the configured battlefield number.')
    parser.add_argument('--accept', action='append', metavar='shovel=rest,radar=0-1', help='Counts, ranges or rest; repeat for alternatives. Replaces configured mixes.')
    parser.add_argument('--tiles', type=int, help='Expected total resource nodes.')
    parser.add_argument('--max-attempts', type=int, default=0, help='0 means continue until a match.')
    parser.add_argument('--inspect', action='store_true', help='Inspect the already-open map once; never abandon it.')
    parser.add_argument('--diagnose', action='store_true', help='Check game and Python privileges without clicking or changing focus.')
    parser.add_argument('--no-prompt', action='store_true', help='Use settings/arguments without asking questions (for unattended runs).')
    parser.add_argument('--early-reject', action=argparse.BooleanOptionalAction, default=None, help='Abandon as soon as all target mixes are impossible.')
    parser.add_argument('--countdown', type=int, help='Seconds to wait after setup (default: 4).')
    args = parser.parse_args()
    if args.diagnose:
        try:
            check_input_privileges(find_game_window())
            print('Privilege check passed. No game actions were performed.')
            return 0
        except (OSError, RuntimeError) as exc:
            print(f'Diagnostic: {exc}', file=sys.stderr)
            return 1
    removed, freed = cleanup_screenshots(ROOT / 'runs')
    cleanup_summaries()
    if removed:
        print(f'Cleaned up {removed} old screenshots ({freed / 1024 ** 2:.1f} MiB).', flush=True)
    config = json.loads(args.config.read_text(encoding='utf-8'))
    for field in ('map', 'tiles'):
        if getattr(args, field) is not None:
            config[field] = getattr(args, field)
    if args.accept:
        config['accept'] = parse_mixes(args.accept, config['tiles'])
    if args.early_reject is not None:
        config['early_reject'] = args.early_reject
    if args.countdown is not None:
        config['countdown_seconds'] = args.countdown
    if not args.no_prompt:
        try:
            prompt_settings(config)
        except (EOFError, KeyboardInterrupt):
            print('\nSetup cancelled. No game actions. Use --no-prompt for unattended runs.')
            return 1
    validate(config)
    if args.inspect:
        config['early_reject'] = False  # Inspection remains a full, non-destructive scan.
    if args.max_attempts < 0:
        parser.error('--max-attempts cannot be negative')
    vision.configure_ocr(config.get('tesseract'))
    run = ROOT / 'runs' / datetime.now().strftime('%Y%m%d-%H%M%S')
    run.mkdir(parents=True, exist_ok=True)
    game = None
    resets_done = 0
    time_spent = 0.0
    stop_reason = 'stopped'
    match_found = expedition_saved = game_closed = False
    try:
        print(f'Ready: map {config["map"]}, {config["tiles"]} tiles; early rejection {"on" if config.get("early_reject", True) else "off"}.', flush=True)
        for remaining in range(config.get('countdown_seconds', 4), 0, -1):
            print(f'Starting in {remaining}... Switch to EXILIUM. Ctrl+C cancels.', flush=True)
            time.sleep(1)
        game = Game()
        print('F8 exits; F9 pauses/resumes. Keep EXILIUM visible and in focus while running.', flush=True)
        if not args.inspect:
            wait_text(game, 'Begin Expedition', (.77, .89, .99, .99))
            reset_started = time.monotonic()
            reset_started_local = datetime.now().astimezone().isoformat(timespec='milliseconds')
        attempt = 0
        while True:
            attempt += 1
            folder = run / str(attempt)
            folder.mkdir()
            print(f'Attempt {attempt}: {config["maps"][str(config["map"])]["name"]}', flush=True)
            if not args.inspect:
                enter(game, config['maps'][str(config['map'])])
            try:
                counts, early_rejected = scan(game, config)
            finally:
                cleanup_screenshots(folder)
            matched = not early_rejected and sum(counts.values()) == config['tiles'] and possible(counts, config['accept'])
            result = {'attempt': attempt, 'map': config['map'], 'counts': counts, 'matched': matched,
                      'tiles_read': sum(counts.values()), 'expected_tiles': config['tiles'], 'early_rejected': early_rejected,
                      'resets_done': resets_done, 'time_spent_seconds': time_spent,
                      'reset_completed': False}
            (folder / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(f'{counts} — {"MATCH: expedition preserved" if matched else "does not match"}', flush=True)
            if matched:
                match_found = True
                import winsound
                winsound.MessageBeep()
            if args.inspect:
                stop_reason = 'inspection complete (match found)' if matched else 'inspection complete'
                return 0
            if matched:
                print('Match found. Choosing Leave For Now, then closing EXILIUM normally.', flush=True)
                leave_for_now(game)
                expedition_saved = True
                result.update(expedition_saved=True, game_closed=False)
                (folder / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
                game.close_window()
                game_closed = True
                result['game_closed'] = True
                (folder / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
                stop_reason = 'match saved; game closed'
                print('Matching expedition saved with Leave For Now. EXILIUM closed.', flush=True)
                return 0
            abandon(game)
            # abandon() returns only after OCR confirms Begin Expedition again.
            reset_finished = time.monotonic()
            reset_finished_local = datetime.now().astimezone().isoformat(timespec='milliseconds')
            reset_seconds = reset_finished - reset_started
            resets_done += 1
            time_spent += reset_seconds
            result.update(reset_completed=True, reset_started_local=reset_started_local,
                          reset_finished_local=reset_finished_local, reset_seconds=reset_seconds,
                          resets_done=resets_done, time_spent_seconds=time_spent)
            # The next cycle starts at this same confirmed return to the main screen.
            reset_started, reset_started_local = reset_finished, reset_finished_local
            (folder / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(f'Reset {resets_done} completed in {reset_seconds:.1f} seconds.', flush=True)
            if args.max_attempts and attempt >= args.max_attempts:
                stop_reason = 'attempt limit reached'
                return 0
    except (KeyboardInterrupt, Exception) as exc:
        stop_reason = str(exc) or ('Ctrl+C' if isinstance(exc, KeyboardInterrupt) else type(exc).__name__)
        print(f'Stopped: {exc or "F8 / Ctrl+C"}. No further game actions.', file=sys.stderr)
        return 1
    finally:
        cleanup_screenshots(run)
        if game:
            game.dispose()
        print(f'\nResets done: {resets_done}\nTime spent (completed resets): {time_spent:.1f} seconds.', flush=True)
        summary = {'stop_reason': stop_reason, 'resets_done': resets_done,
                   'match_found': match_found, 'expedition_saved': expedition_saved, 'game_closed': game_closed,
                   'time_spent_seconds': time_spent,
                   'finished_local': datetime.now().astimezone().isoformat(timespec='milliseconds')}
        try:
            (run / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
            cleanup_summaries()
        except OSError as exc:
            print(f'Could not save summary: {exc}', file=sys.stderr)


if __name__ == '__main__':
    sys.exit(main())
