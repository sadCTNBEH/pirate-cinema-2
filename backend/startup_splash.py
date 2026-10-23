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

    def _run(self) -> None:
        form = None
        image = None
        try:
            import clr

            clr.AddReference("System.Drawing")
            clr.AddReference("System.Windows.Forms")
            import time
            from System.Drawing import Bitmap, Color, Size
            from System.Windows.Forms import (
                Application,
                Form,
                FormBorderStyle,
                FormStartPosition,
                ImageLayout,
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

            form.Show()
            form.Refresh()
            Application.DoEvents()
            self._started.set()

            start_t = time.time()
            # Плавный цикл DoEvents вместо блокирующего Application.Run:
            # закрытие сплэша никогда не вызывает Application.Exit() и не трогает главное окно
            while not self._close_requested.is_set():
                Application.DoEvents()
                time.sleep(0.04)
                if time.time() - start_t > 3.0:
                    break
        except Exception:
            logger.exception("Startup splash is unavailable")
            self._started.set()
        finally:
            self._form = None
            if form is not None:
                try:
                    form.Hide()
                    form.Dispose()
                except Exception:
                    pass
            if image is not None:
                try:
                    image.Dispose()
                except Exception:
                    pass

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

