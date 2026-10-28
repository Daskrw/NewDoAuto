"""
Emergency stop and safety guards for NewDoAuto execution.
Provides global hotkey registration (e.g. F12 or Ctrl+F12) to trigger immediate cooperative cancellation.
"""

from typing import Optional
import ctypes
from ctypes import wintypes
import threading
import time
from newdoauto.core.state import CancellationToken
from newdoauto.core.logger import StructuredLogger


class EmergencyStopListener:
    """
    Listens for a designated global hotkey (e.g., F12 = 0x7B) using Win32 RegisterHotKey
    in a dedicated message-pump thread to trigger immediate cancellation.
    """

    def __init__(self, token: CancellationToken, hotkey_vk: int = 0x7B, modifiers: int = 0x0002):
        """
        hotkey_vk: Virtual key code. Default 0x7B = VK_F12.
        modifiers: 0x0002 = MOD_CONTROL. (Ctrl+F12)
        """
        self.token = token
        self.hotkey_vk = hotkey_vk
        self.modifiers = modifiers
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._hotkey_id = 1001

    def start(self, logger: Optional[StructuredLogger] = None) -> bool:
        """Starts the global hotkey listener thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run_message_loop, args=(logger,), daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """Stops the listener and unregisters the hotkey."""
        self._running = False
        # Post WM_QUIT to ensure GetMessage unblocks
        if self._thread and self._thread.is_alive():
            ctypes.windll.user32.PostQuitMessage(0)

    def _run_message_loop(self, logger: Optional[StructuredLogger]):
        user32 = ctypes.windll.user32
        MOD_NOREPEAT = 0x4000

        # Try RegisterHotKey
        success = user32.RegisterHotKey(
            None,
            self._hotkey_id,
            self.modifiers | MOD_NOREPEAT,
            self.hotkey_vk,
        )

        if not success and logger:
            logger.debug("RegisterHotKey returned false (may be in non-interactive session or hotkey taken)")

        msg = wintypes.MSG()
        while self._running:
            # Check for message with 100ms timeout
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE = 1
                if msg.message == 0x0312:  # WM_HOTKEY
                    if logger:
                        logger.warn("EMERGENCY STOP HOTKEY TRIGGERED! Aborting workflow execution immediately.")
                    self.token.cancel("Emergency stop hotkey pressed (Ctrl+F12)")
                    break
                elif msg.message == 0x0012:  # WM_QUIT
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.05)

        try:
            user32.UnregisterHotKey(None, self._hotkey_id)
        except Exception:
            pass
