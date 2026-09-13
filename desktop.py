"""Windows client-area capture and held-button input for EXILIUM."""
import ctypes
from ctypes import wintypes as W
import os
import time
import threading

from PIL import ImageGrab

FOCUS_GRACE_SECONDS = 3.0

u = ctypes.WinDLL('user32', use_last_error=True)
u.SetProcessDPIAware()
u.GetForegroundWindow.restype = W.HWND
u.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]
u.GetClientRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
u.ClientToScreen.argtypes = [W.HWND, ctypes.POINTER(W.POINT)]
u.SetForegroundWindow.argtypes = [W.HWND]
u.IsWindow.argtypes = [W.HWND]
u.IsIconic.argtypes = [W.HWND]
u.IsWindowVisible.argtypes = [W.HWND]
u.mouse_event.argtypes = [W.DWORD, W.DWORD, W.DWORD, W.DWORD, ctypes.c_size_t]
u.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
u.PostMessageW.restype = W.BOOL
u.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
u.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]
u.GetCursorPos.argtypes = [ctypes.POINTER(W.POINT)]
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u.WindowFromPoint.argtypes = [W.POINT]
u.WindowFromPoint.restype = W.HWND
u.GetAncestor.argtypes = [W.HWND, W.UINT]
u.GetAncestor.restype = W.HWND

k = ctypes.WinDLL('kernel32', use_last_error=True)
a = ctypes.WinDLL('advapi32', use_last_error=True)
k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k.OpenProcess.restype = W.HANDLE
k.CloseHandle.argtypes = [W.HANDLE]
k.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD)]
a.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, ctypes.POINTER(W.HANDLE)]
a.GetTokenInformation.argtypes = [W.HANDLE, ctypes.c_int, W.LPVOID, W.DWORD, ctypes.POINTER(W.DWORD)]


def process_elevated(pid):
    """Query only token metadata; works for an elevated game from normal Python."""
    process = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not process:
        raise ctypes.WinError(ctypes.get_last_error())
    token = W.HANDLE()
    try:
        if not a.OpenProcessToken(process, 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
            raise ctypes.WinError(ctypes.get_last_error())
        elevated, size = W.DWORD(), W.DWORD()
        if not a.GetTokenInformation(token, 20, ctypes.byref(elevated),
                                     ctypes.sizeof(elevated), ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return bool(elevated.value)
    finally:
        if token:
            k.CloseHandle(token)
        k.CloseHandle(process)


def find_game_window():
    found = []
    callback = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    @callback
    def visit(hwnd, _):
        title = ctypes.create_unicode_buffer(256)
        u.GetWindowTextW(hwnd, title, 256)
        if title.value == 'EXILIUM' and u.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True
    u.EnumWindows(visit, 0)
    if len(found) != 1:
        raise RuntimeError(f'Expected one EXILIUM window; found {len(found)}.')
    return found[0]


def check_input_privileges(hwnd):
    pid = W.DWORD()
    if not u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
        raise ctypes.WinError(ctypes.get_last_error())
    game_elevated = process_elevated(pid.value)
    script_elevated = process_elevated(os.getpid())
    print(f'Administrator rights: EXILIUM={game_elevated}, Python={script_elevated}.', flush=True)
    if game_elevated and not script_elevated:
        raise RuntimeError(
            'EXILIUM is running as administrator but Python is not. Windows blocks '
            'the script\'s mouse input. Close the game and launcher, disable '
            '"Run this program as an administrator" in their Compatibility properties, '
            'then reopen them normally. Alternatively, run this script as administrator '
            'if the game requires it. CMD versus PowerShell does not matter.')


def window_description(hwnd):
    if not hwnd:
        return 'no foreground window (Windows returned NULL)'
    title, cls = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(256)
    pid = W.DWORD()
    u.GetWindowTextW(hwnd, title, 256)
    u.GetClassNameW(hwnd, cls, 256)
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    executable = 'unknown process'
    process = k.OpenProcess(0x1000, False, pid.value)
    if process:
        try:
            path, size = ctypes.create_unicode_buffer(32768), W.DWORD(32768)
            if k.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size)):
                executable = os.path.basename(path.value)
        finally:
            k.CloseHandle(process)
    return f'{title.value or "untitled"!r} (process={executable}, PID={pid.value}, class={cls.value!r}, HWND={hwnd})'


class Game:
    def __init__(self):
        self.hwnd = find_game_window()
        check_input_privileges(self.hwnd)
        self._pause = threading.Event()
        self._exit = threading.Event()
        self._shutdown = threading.Event()
        self._mouse_down = False
        self._last_input = 'none'
        self._last_move = 'none'
        self._resume_generation = 0
        self.paused_seconds = 0.0
        self._keys = threading.Thread(target=self._watch_keys, daemon=True)
        self._keys.start()
        try:
            u.SetForegroundWindow(self.hwnd)
            time.sleep(.4)
            if u.GetForegroundWindow() != self.hwnd or u.IsIconic(self.hwnd):
                print('Windows did not focus EXILIUM. Switch to the game within 15 seconds.', flush=True)
                deadline = self.active_clock() + 15
                while u.GetForegroundWindow() != self.hwnd or u.IsIconic(self.hwnd):
                    self.hotkeys()
                    if not u.IsWindow(self.hwnd) or self.active_clock() >= deadline:
                        raise RuntimeError('EXILIUM did not receive focus. Open it and rerun the script.')
                    time.sleep(.05)
            self.check()
        except BaseException:
            self.dispose()
            raise

    def _watch_keys(self):
        previous_f9 = False
        while not self._shutdown.is_set():
            if u.GetAsyncKeyState(0x77) & 0x8000:
                self._exit.set()
            f9 = bool(u.GetAsyncKeyState(0x78) & 0x8000)
            if f9 and not previous_f9:
                if self._pause.is_set():
                    self._pause.clear()
                else:
                    self._pause.set()
                    print('F9 pause requested; finishing any held mouse gesture first.', flush=True)
            previous_f9 = f9
            self._shutdown.wait(.025)

    def dispose(self):
        self._shutdown.set()
        self._keys.join(timeout=1)

    def active_clock(self):
        """Exclude paused time from screen-loading deadlines, not run totals."""
        return time.monotonic() - self.paused_seconds

    def hotkeys(self):
        if self._exit.is_set() or u.GetAsyncKeyState(0x77) & 0x8000:
            raise KeyboardInterrupt('F8 exit requested')
        # Finish an in-flight click/drag before pausing, so no button stays held.
        if self._pause.is_set() and not self._mouse_down:
            started = time.monotonic()
            print('Paused. Return to EXILIUM and press F9 to resume; F8 exits.', flush=True)
            try:
                while self._pause.is_set():
                    if self._exit.is_set():
                        raise KeyboardInterrupt('F8 exit requested')
                    time.sleep(.05)
            finally:
                self.paused_seconds += time.monotonic() - started
            if self._exit.is_set():
                raise KeyboardInterrupt('F8 exit requested')
            self._resume_generation += 1
            print('Resumed.', flush=True)

    def check(self):
        self.hotkeys()
        if not u.IsWindow(self.hwnd):
            raise RuntimeError('EXILIUM window closed. Stopped.')
        if u.IsIconic(self.hwnd):
            raise RuntimeError('EXILIUM was minimized. Stopped.')
        foreground = u.GetForegroundWindow()
        # Loading/activation can briefly leave NULL or a shell window in the
        # foreground. Wait without moving, clicking, or stealing focus. A held
        # gesture must instead fail immediately so its finally block releases it.
        first_foreground = foreground
        if foreground != self.hwnd and not self._mouse_down:
            started = self.active_clock()
            try:
                while foreground != self.hwnd and self.active_clock() - started < FOCUS_GRACE_SECONDS:
                    self.hotkeys()
                    if not u.IsWindow(self.hwnd) or u.IsIconic(self.hwnd):
                        break
                    time.sleep(.05)
                    foreground = u.GetForegroundWindow()
            finally:
                self.paused_seconds += self.active_clock() - started
        if not u.IsWindow(self.hwnd):
            raise RuntimeError('EXILIUM window closed. Stopped.')
        if u.IsIconic(self.hwnd):
            raise RuntimeError('EXILIUM was minimized. Stopped.')
        if foreground != self.hwnd:
            raise RuntimeError(f'EXILIUM lost focus to {window_description(foreground)}. '
                               f'First foreground: {window_description(first_foreground)}. '
                               f'Last input: {self._last_input}. '
                               'Input stopped; this does not establish why focus changed.')

    def bounds(self):
        self.check()
        rect, origin = W.RECT(), W.POINT()
        if not u.GetClientRect(self.hwnd, ctypes.byref(rect)) or not u.ClientToScreen(self.hwnd, ctypes.byref(origin)):
            raise ctypes.WinError()
        return origin.x, origin.y, rect.right, rect.bottom

    def capture(self):
        x, y, w, h = self.bounds()
        return ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)

    def wait(self, seconds):
        end = self.active_clock() + seconds
        while self.active_clock() < end:
            self.check()
            time.sleep(.05)

    def move(self, point):
        x, y, w, h = self.bounds()
        if not all(0 < p < 1 for p in point):
            raise ValueError('Mouse coordinates must be inside the client area.')
        target = (x + round(point[0] * w), y + round(point[1] * h))
        self._last_move = f'move to {target}, normalized={point}, client={(x, y, w, h)}'
        self._last_input = self._last_move
        if not u.SetCursorPos(*target):
            raise ctypes.WinError(ctypes.get_last_error())
        self._cursor_target = target
        self._cursor_point = point
        self._pointer_generation = self._resume_generation

    def verify_pointer(self, action):
        """Do not click a taskbar/overlay if cursor placement failed or was intercepted."""
        self.check()
        # F9 permits using the mouse in other apps while paused. Reposition to
        # the intended game point once on resume, then apply the same checks.
        if getattr(self, '_pointer_generation', 0) != getattr(self, '_resume_generation', 0):
            self.move(self._cursor_point)
        cursor = W.POINT()
        if not u.GetCursorPos(ctypes.byref(cursor)):
            raise ctypes.WinError(ctypes.get_last_error())
        actual = (cursor.x, cursor.y)
        target = self._cursor_target
        if max(abs(a - b) for a, b in zip(actual, target)) > 2:
            raise RuntimeError(f'Cursor did not stay at the game target: requested={target}, '
                               f'actual={actual}. Blocked {action}; last input: {self._last_input}.')
        under_pointer = u.WindowFromPoint(cursor)
        if u.GetAncestor(under_pointer, 2) != self.hwnd:  # GA_ROOT
            raise RuntimeError(f'Blocked {action} at {actual}: pointer is over '
                               f'{window_description(under_pointer)}, not EXILIUM. '
                               f'Last input: {self._last_input}.')
        self._last_input = f'{action} at {actual}; {self._last_move}'

    def click(self, point):
        self.move(point)
        self.verify_pointer('click')
        try:
            self._mouse_down = True
            u.mouse_event(2, 0, 0, 0, 0)
            self.wait(.08)
        finally:
            u.mouse_event(4, 0, 0, 0, 0)
            self._mouse_down = False
        self.wait(.3)

    def zoom_out(self):
        self.move((.54, .50))
        for _ in range(30):
            self.verify_pointer('zoom wheel')
            u.mouse_event(0x0800, 0, 0, ctypes.c_uint32(-120).value, 0)
            self.wait(.08)
        self.wait(.5)

    def drag(self, start, end, duration=1.2):
        self.move(start)
        self.wait(.15)
        self.verify_pointer('drag start')
        try:
            self._mouse_down = True
            u.mouse_event(2, 0, 0, 0, 0)
            self.wait(.25)
            # wait() polls every 50 ms; 60 steps previously stretched movement
            # to at least 3 seconds, regardless of the requested duration.
            steps = max(1, round(duration / .05))
            for i in range(1, steps + 1):
                f = i / steps
                self.move(tuple(a + (b - a) * f for a, b in zip(start, end)))
                self.wait(duration / steps)
            self.wait(.15)
        finally:
            u.mouse_event(4, 0, 0, 0, 0)
            self._mouse_down = False
        self.wait(.4)

    def close_window(self):
        """Request a normal shutdown (the title-bar X), never force-kill."""
        self.check()
        if not u.PostMessageW(self.hwnd, 0x0010, 0, 0):  # WM_CLOSE
            raise ctypes.WinError(ctypes.get_last_error())
        deadline = self.active_clock() + 15
        while u.IsWindow(self.hwnd):
            self.hotkeys()  # Focus normally changes while the game closes.
            if self.active_clock() >= deadline:
                raise RuntimeError('Expedition saved, but EXILIUM did not close. Check for an exit dialog; no force-kill was used.')
            time.sleep(.1)
