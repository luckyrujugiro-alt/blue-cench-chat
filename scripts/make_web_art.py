"""Exports the code-drawn characters, chat wallpapers and seals for the phone web app."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from bluecenchchat.ui.components.badges import seal_pixmap  # noqa: E402
from bluecenchchat.ui.components.characters import NAMES, draw_character  # noqa: E402
from bluecenchchat.ui.components.wallpaper import doodle_tile  # noqa: E402

out = Path(__file__).resolve().parents[1] / "bluecenchchat" / "web" / "static" / "art"
out.mkdir(parents=True, exist_ok=True)
for i in range(len(NAMES)):
    draw_character(i, 160).save(str(out / f"c{i}.png"), "PNG")
doodle_tile("#1E6BFF", 26, "#F4F7FC").save(str(out / "wall-light.png"), "PNG")
doodle_tile("#FFFFFF", 30, "#000000").save(str(out / "wall-dark.png"), "PNG")
doodle_tile("#4DB2FF", 30, "#060E24").save(str(out / "wall-midnight.png"), "PNG")
seal_pixmap(32, "verified", 2.0).save(str(out / "seal.png"), "PNG")
seal_pixmap(32, "founder", 2.0).save(str(out / "seal-founder.png"), "PNG")
print("exported to", out)
