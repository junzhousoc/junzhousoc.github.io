import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bs4 import BeautifulSoup
from sync import Mirror, main
from validate import validate_site
from test_sync import PAGE, CONFIG, SOURCE, loader


def rehash(root):
    path = root / 'sync-manifest.json'
    manifest = json.loads(path.read_text())
    manifest['files'] = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in root.rglob('*') if p.is_file() and p != path}
    path.write_text(json.dumps(manifest))


class AuditTests(unittest.TestCase):
    def test_text_image_link_and_new_page_updates_are_copied(self):
        changed = PAGE.replace('Published biography', 'Updated biography with new research')
        changed = changed.replace('image.png', 'new-image.png').replace('>Research</a>', '>Updated research link</a>')
        changed = changed.replace('</nav>', '<a href="/view/jun-zhou-/new-publication">New publication</a></nav>')
        def updated(url):
            if url.endswith('new-image.png'):
                return b'new-image-content', 'image/png', url
            if url.endswith('favicon.png'):
                return loader(url)
            return changed.encode(), 'text/html', url
        with tempfile.TemporaryDirectory() as directory:
            mirror = Mirror(CONFIG, directory, updated)
            mirror.run()
            root = Path(directory)
            page = (root / 'about.html').read_text()
            self.assertIn('Updated biography with new research', page)
            self.assertIn('Updated research link', page)
            self.assertTrue((root / 'new-publication.html').exists())
            self.assertIn(b'new-image-content', [p.read_bytes() for p in (root / 'assets').glob('*.png')])
            validate_site(root)

    def test_repeated_source_produces_identical_snapshot(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            Mirror(CONFIG, first, loader).run()
            Mirror(CONFIG, second, loader).run()
            self.assertEqual((Path(first) / 'sync-manifest.json').read_bytes(),
                             (Path(second) / 'sync-manifest.json').read_bytes())

    def test_chinese_page_names_and_encoded_urls(self):
        seen = []
        changed = PAGE.replace('</nav>', '<a href="/view/jun-zhou-/%E7%8F%BA">珺</a></nav>')
        def localized(url):
            seen.append(url)
            if url.endswith(('image.png', 'favicon.png')):
                return loader(url)
            return changed.encode(), 'text/html', url
        with tempfile.TemporaryDirectory() as directory:
            Mirror(CONFIG, directory, localized).run()
            self.assertTrue((Path(directory) / '珺.html').exists())
            self.assertTrue(any('/%E7%8F%BA' in url for url in seen))

    def test_failed_run_preserves_previous_local_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'config.json'; config.write_text(json.dumps(CONFIG))
            site = root / 'site';site.mkdir(); (site / 'index.html').write_text('Last good version')
            with patch('sys.argv', ['sync.py', '--config', str(config), '--output', str(site)]), patch.object(Mirror, 'run', side_effect=OSError('Source unavailable')):
                with self.assertRaises(OSError):main()
            self.assertEqual((site / 'index.html').read_text(), 'Last good version')
            self.assertFalse(list(root.glob('.sync-*')))

    def test_missing_resource_stops_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);Mirror(CONFIG, root, loader).run()
            page=BeautifulSoup((root/'index.html').read_text(),'html.parser')
            (root/page.img['src']).unlink();rehash(root)
            with self.assertRaisesRegex(ValueError,'Missing local resource'):validate_site(root)

    def test_changed_file_fails_integrity_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);Mirror(CONFIG, root, loader).run()
            (root/'about.html').write_text('Unexpected change')
            with self.assertRaisesRegex(ValueError,'checksum mismatch'):validate_site(root)

    def test_executable_links_are_rejected(self):
        changed=PAGE.replace('https://www.junzhou.space/research#article','javascript:alert(1)')
        def unsafe(url):
            if url.endswith(('image.png','favicon.png')):return loader(url)
            return changed.encode(),'text/html',url
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'Unsafe URL scheme'):Mirror(CONFIG,directory,unsafe).run()

    def test_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);Mirror(CONFIG,root,loader).run()
            (root/'escape').symlink_to('/tmp')
            with self.assertRaisesRegex(ValueError,'symbolic links'):validate_site(root)
