import tempfile
import hashlib
from sync import BASE
import unittest
from pathlib import Path
from sync import Mirror

SOURCE = 'https://sites.google.com/view/jun-zhou-'
CONFIG = {'source_url': SOURCE, 'previous_domains': ['www.junzhou.space'], 'required_pages': ['about']}
PAGE = '''<html><head><title>about</title><style nonce="volatile">body{color:black}</style></head>
<body><nav><a href="/view/jun-zhou-/about">about</a><a href="/view/jun-zhou-/research">research</a></nav>
<div class="theme"><div><section><h1><div class="CjVfdc"><div class="PPhIP">Copy heading link</div><span>Jun Zhou</span></div></h1><p>Published biography</p>
<a href="https://www.junzhou.space/research#article">Research</a>
<img src="https://sites.google.com/image.png"><iframe data-src="https://drive.google.com/file/d/public/preview"></iframe>
<script>window.bad=true</script></section></div></div></body></html>'''


def loader(url):
    if url.endswith('image.png'):
        return b'fixture-image', 'image/png', url
    return PAGE.encode(), 'text/html', url


class MirrorTests(unittest.TestCase):
    def test_pages_links_assets_and_iframe_are_portable(self):
        with tempfile.TemporaryDirectory() as directory:
            mirror = Mirror(CONFIG, directory, loader)
            mirror.run()
            page = (Path(directory) / 'about.html').read_text()
            self.assertIn('href="research.html#article"', page)
            self.assertIn('<span>Jun Zhou</span>', page)
            self.assertNotIn('Copy heading link', page)
            self.assertNotIn('www.junzhou.space', page)
            self.assertNotIn('data-src', page)
            self.assertNotIn('<script', page)
            self.assertNotIn('nonce=', page)
            self.assertIn('src="https://drive.google.com/file/d/public/preview"', page)
            self.assertIn('src="assets/', page)
            self.assertEqual(set(mirror.pages), {'', 'about', 'research'})

    def test_missing_required_page_stops_build(self):
        with tempfile.TemporaryDirectory() as directory:
            mirror = Mirror(dict(CONFIG, required_pages=['deleted-page']), directory, loader)
            with self.assertRaisesRegex(ValueError, 'Missing required'):
                mirror.run()

    def test_login_page_is_not_accepted(self):
        def login(url):
            return b'<html>Sign in</html>', 'text/html', 'https://accounts.google.com/login'
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'redirected'):
                Mirror(CONFIG, directory, login).run()

    def test_broken_image_stops_build(self):
        def broken(url):
            if url.endswith('image.png'):
                raise OSError('Image inaccessible')
            return loader(url)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(OSError, 'Image inaccessible'):
                Mirror(CONFIG, directory, broken).run()

    def test_content_hash_does_not_depend_on_resource_url(self):
        with tempfile.TemporaryDirectory() as directory:
            mirror = Mirror(CONFIG, directory, lambda u: (b'identical', 'image/png', u))
            self.assertEqual(mirror.asset('https://sites.google.com/token-one.png'),
                             mirror.asset('https://sites.google.com/token-two.png'))

    def test_signed_images_are_refreshed_before_download(self):
        def expiring(url):
            if 'expired.png' in url:
                raise OSError('Expired signed URL must not be used')
            if url.endswith('image.png'):
                return loader(url)
            page = PAGE if 'mirror_refresh=' in url else PAGE.replace('image.png', 'expired.png')
            return page.encode(), 'text/html', url
        with tempfile.TemporaryDirectory() as directory:
            Mirror(CONFIG, directory, expiring).run()

    def test_navigation_styles_have_content_addressed_url(self):
        with tempfile.TemporaryDirectory() as directory:
            mirror = Mirror(CONFIG, directory, loader)
            mirror.run()
            css = (BASE / 'scripts/mirror.css').read_bytes()
            digest = hashlib.sha256(css).hexdigest()[:24]
            self.assertIn('mirror-' + digest + '.css', (Path(directory) / 'index.html').read_text())
            self.assertEqual((Path(directory) / mirror.override_css).read_bytes(), css)

    def test_nested_page_link_and_path_safety(self):
        with tempfile.TemporaryDirectory() as directory:
            mirror = Mirror(CONFIG, directory, loader)
            self.assertIsNone(mirror.page_path('https://other.example/about'))
            self.assertEqual(mirror.page_path(SOURCE + '/research/one'), 'research/one')
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                mirror.page_path(SOURCE + '/%2e%2e/secret')


if __name__ == '__main__':
    unittest.main()
