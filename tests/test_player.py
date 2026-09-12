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

    def test_home_has_settings_instead_of_a_folders_card(self):
        self.assertNotIn('Folders', player.App.categories)
        self.assertEqual(player.App.categories[-1], 'Settings')

    def test_media_extensions_are_supported(self):
        self.assertIn('.mp4', player.MEDIA_EXTENSIONS)
        self.assertIn('.jpg', player.MEDIA_EXTENSIONS)
        self.assertIn('.webp', player.MEDIA_EXTENSIONS)

    def test_audio_extensions_are_separate(self):
        self.assertNotIn('.mp3', player.MEDIA_EXTENSIONS)
        self.assertNotIn('.flac', player.MEDIA_EXTENSIONS)

    def test_search_matches_song_metadata_media_albums_and_artists(self):
        class SearchData:
            tracks = ['/music/one.mp3', '/music/two.mp3']
            media = ['/video/Concert.mp4', '/video/Sunrise.jpg']
            metadata = {
                '/music/one.mp3': {'title': 'First Song', 'artist': 'The Example', 'album': 'Debut'},
                '/music/two.mp3': {'title': 'Second Song', 'artist': 'Another Artist', 'album': 'More'},
            }

            def track_title(self, path):
                return self.metadata[path]['title']

            def song_rows(self, paths):
                return [(self.track_title(path), 'track', path) for path in paths]

            def media_rows(self, paths):
                return [(Path(path).stem, 'media', path) for path in paths]

        data = SearchData()
        self.assertEqual(player.App.search_results(data, 'All Songs', 'example')[0][2], '/music/one.mp3')
        self.assertEqual(player.App.search_results(data, 'Media', 'concert')[0][2], '/video/Concert.mp4')
        self.assertEqual(player.App.search_results(data, 'Albums', 'debut')[0][0], 'Debut')
        self.assertEqual(player.App.search_results(data, 'Artists', 'another')[0][0], 'Another Artist')


if __name__ == '__main__':
    unittest.main()
