"""Generate delivery sizes from the supplied logo without changing its artwork."""
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[1]
source = root / 'logo' / 'Gemini_Generated_Image_gzm9c8gzm9c8gzm9.png'
with Image.open(source) as original:
    image = original.convert('RGB')
    assets = {
        'frontend/public/brand/logo.png': 512,
        'frontend/public/brand/icon-192.png': 192,
        'frontend/public/brand/icon-512.png': 512,
        'frontend/public/brand/apple-touch-icon.png': 180,
        'frontend/public/brand/favicon-32.png': 32,
        'mobile/assets/logo.png': 512,
        'mobile/assets/icon.png': 1024,
        'backend/fleet/assets/logo.png': 256,
    }
    for relative, size in assets.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.resize((size, size), Image.Resampling.LANCZOS).save(destination, optimize=True)
        print(relative, size)
    image.resize((48, 48), Image.Resampling.LANCZOS).save(root / 'frontend/public/favicon.ico', sizes=[(16,16),(32,32),(48,48)])
    adaptive = Image.new('RGB', (1024, 1024), '#102C42')
    adaptive.paste(image.resize((640, 640), Image.Resampling.LANCZOS), (192, 192))
    adaptive.save(root / 'mobile/assets/adaptive-icon.png', optimize=True)
