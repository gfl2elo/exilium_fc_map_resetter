"""Windows client-area capture and held-button input for EXILIUM."""
import ctypes
from ctypes import wintypes as W
import time
import threading

from PIL import ImageGrab

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


class Game:
    def __init__(self):
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
        self.hwnd = found[0]
        self._pause = threading.Event()
        self._exit = threading.Event()
        self._shutdown = threading.Event()
        self._mouse_down = False
        self.paused_seconds = 0.0
        self._keys = threading.Thread(target=self._watch_keys, daemon=True)
        u.SetForegroundWindow(self.hwnd)
        time.sleep(.4)
        self.check()
        self._keys.start()

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
            print('Resumed.', flush=True)

    def check(self):
        self.hotkeys()
        if not u.IsWindow(self.hwnd) or u.IsIconic(self.hwnd) or u.GetForegroundWindow() != self.hwnd:
            raise RuntimeError('EXILIUM lost focus or is unavailable. Stopped.')

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
        u.SetCursorPos(x + round(point[0] * w), y + round(point[1] * h))

    def click(self, point):
        self.move(point)
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
            self.check()
            u.mouse_event(0x0800, 0, 0, ctypes.c_uint32(-120).value, 0)
            self.wait(.08)
        self.wait(.5)

    def drag(self, start, end, duration=1.2):
        self.move(start)
        self.wait(.15)
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
