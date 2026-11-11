"""Generate web and Android icons from the supplied/official IIT raster logo.
Development utility only: python -m pip install Pillow; python scripts/generate_icons.py.
The original is 269 x 71; scaling does not add detail or redraw the institute mark.
"""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Image.open(ROOT / 'assets/iit-logo-source.png').convert('RGBA')
LOGO = SOURCE.crop(SOURCE.getbbox())
SHIELD = SOURCE.crop((16, 13, 55, 64))
PUBLIC = ROOT / 'public/icons'
LOGO.save(PUBLIC / 'iit-logo.png')
SHIELD.save(PUBLIC / 'iit-shield.png')


def icon(size, foreground=False):
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0) if foreground else '#152d42')
    # Adaptive Android foreground stays within the central 66/108 safe circle.
    width, height = (.35, .46) if foreground else (.42, .55)
    symbol = SHIELD.resize((round(size * width), round(size * height)), Image.Resampling.LANCZOS)
    image.alpha_composite(symbol, ((size - symbol.width) // 2, (size - symbol.height) // 2))
    return image


for name, size in [('icon-192.png', 192), ('icon-512.png', 512), ('icon-maskable-512.png', 512), ('apple-touch-icon.png', 180), ('favicon-32.png', 32)]:
    icon(size).save(PUBLIC / name)
for density, size in [('mdpi', 48), ('hdpi', 72), ('xhdpi', 96), ('xxhdpi', 144), ('xxxhdpi', 192)]:
    folder = ROOT / f'android/app/src/main/res/mipmap-{density}'
    icon(size).save(folder / 'ic_launcher.png')
    icon(size).save(folder / 'ic_launcher_round.png')
    icon(round(size * 108 / 48), foreground=True).save(folder / 'ic_launcher_foreground.png')
