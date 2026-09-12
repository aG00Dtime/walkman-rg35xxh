import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import player
except ModuleNotFoundError as error:
    if error.name != 'pygame':
        raise
    player = None


@unittest.skipUnless(player is not None, 'pygame is provided by the KNULLI device runtime')
class PlayerSurfaceTests(unittest.TestCase):
    def test_library_has_media_section(self):
        self.assertIn('Media', player.App.categories)

    def test_media_extensions_are_supported(self):
        self.assertIn('.mp4', player.MEDIA_EXTENSIONS)
        self.assertIn('.jpg', player.MEDIA_EXTENSIONS)
        self.assertIn('.webp', player.MEDIA_EXTENSIONS)

    def test_audio_extensions_are_separate(self):
        self.assertIn('.mp3', player.AUDIO_EXTENSIONS)
        self.assertNotIn('.mp3', player.MEDIA_EXTENSIONS)


if __name__ == '__main__':
    unittest.main()
