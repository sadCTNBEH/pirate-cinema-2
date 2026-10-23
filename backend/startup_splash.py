"""Small native startup screen shown while the desktop application initializes."""

from __future__ import annotations

import logging
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class StartupSplash:
    """A Windows Forms splash screen with a clean color-keyed PNG silhouette."""

    def __init__(self, logo_path: Path):
        self._logo_path = logo_path
        self._close_requested = threading.Event()
        self._started = threading.Event()
        self._thread: Any = None
        self._form: Any = None

    def start(self) -> None:
        if sys.platform != "win32":
            return

        try:
            import clr

            clr.AddReference("System")
            from System.Threading import ApartmentState, Thread, ThreadStart

            thread = Thread(ThreadStart(self._run))
            thread.SetApartmentState(ApartmentState.STA)
            thread.IsBackground = True
            self._thread = thread
            thread.Start()
            self._started.wait(timeout=1.0)
        except (ImportError, OSError, RuntimeError) as error:
            logger.debug("Startup splash is unavailable: %s", error)
            self._started.set()

    def close(self) -> None:
        self._close_requested.set()
        form = self._form
        if form is not None:
            try:
                if not form.IsDisposed:
                    import System

                    form.BeginInvoke(System.Action(form.Close))
            except (AttributeError, OSError, RuntimeError) as error:
                logger.debug("Could not close startup splash: %s", error)

        thread = self._thread
        if thread is not None and thread.IsAlive:
            thread.Join(500)

    def _run(self) -> None:
        form = None
        image = None
        safety_timer = None
        try:
            import clr

            clr.AddReference("System.Drawing")
            clr.AddReference("System.Windows.Forms")
            from System.Drawing import Bitmap, Color, Size
            from System.Windows.Forms import (
                Application,
                Form,
                FormBorderStyle,
                FormStartPosition,
                ImageLayout,
                Timer as WinFormsTimer,
            )

            image = self._load_keyed_image(Bitmap)
            form = Form()
            form.FormBorderStyle = getattr(FormBorderStyle, "None")
            form.BackColor = Color.Lime
            form.TransparencyKey = Color.Lime
            form.ClientSize = Size(image.Width, image.Height)
            form.BackgroundImage = image
            form.BackgroundImageLayout = ImageLayout.Center
            form.StartPosition = FormStartPosition.CenterScreen
            form.ShowInTaskbar = False
            form.TopMost = True
            self._form = form

            # Встроенный предохранитель: закрыть сплэш максимум через 3 сек
            safety_timer = WinFormsTimer()
            safety_timer.Interval = 3000

            def _on_safety_tick(s, a):
                try:
                    if safety_timer is not None:
                        safety_timer.Stop()
                    if form is not None and not form.IsDisposed:
                        form.Close()
                except Exception:
                    pass

            safety_timer.Tick += _on_safety_tick
            safety_timer.Start()

            form.Show()
            form.Refresh()
            Application.DoEvents()
            self._started.set()

            if not self._close_requested.is_set():
                Application.Run(form)
        except Exception:
            logger.exception("Startup splash is unavailable")
            self._started.set()
        finally:
            if safety_timer is not None:
                try:
                    safety_timer.Stop()
                    safety_timer.Dispose()
                except Exception:
                    pass
            self._form = None
            if image is not None:
                image.Dispose()
            if form is not None:
                form.Dispose()

    def _load_keyed_image(self, bitmap_type: Any) -> Any:
        """Convert alpha to an exact color key without resampling it again in WinForms."""
        if not self._logo_path.is_file():
            raise FileNotFoundError(f"Splash logo is missing: {self._logo_path}")

        from PIL import Image

        with Image.open(self._logo_path).convert("RGBA") as source:
            source.thumbnail((400, 400), Image.Resampling.LANCZOS)
            keyed = Image.new("RGB", source.size, (0, 255, 0))
            visible = source.getchannel("A").point(lambda alpha: 255 if alpha >= 128 else 0)
            keyed.paste(source.convert("RGB"), mask=visible)

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                temp_path = Path(temp_file.name)
                keyed.save(temp_file, format="PNG")

        try:
            loaded = bitmap_type.FromFile(str(temp_path))
            try:
                return bitmap_type(loaded)
            finally:
                loaded.Dispose()
        finally:
            temp_path.unlink(missing_ok=True)

