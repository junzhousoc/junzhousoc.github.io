#!/usr/bin/env python3
"""Mirror published Google Sites pages. Never reads the editor or draft content."""
import argparse
import hashlib
import html
import json
import mimetypes
import re
import shutil
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlsplit, quote
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup
from validate import validate_site

BASE = Path(__file__).resolve().parent.parent
CSS_URL = re.compile(r'url\(\s*[\"\']?([^\)\"\']+)[\"\']?\s*\)')


def fetch(url):
    if urlsplit(url).scheme != 'https':
        raise ValueError(f'Expected an HTTPS resource: {url}')
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://sites.google.com/', 'Cache-Control': 'no-cache'}), timeout=40) as response:
                data = response.read(25_000_001)
                if len(data) > 25_000_000:
                    raise ValueError(f'Resource exceeds 25 MB: {url}')
                return data, response.headers.get_content_type(), response.url
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


class Mirror:
    def __init__(self, config, destination, loader=fetch):
        self.source = config['source_url'].rstrip('/')
        parsed = urlsplit(self.source)
        if parsed.netloc != 'sites.google.com' or not parsed.path.startswith('/view/'):
            raise ValueError('source_url must be a public https://sites.google.com/view/... address')
        self.prefix = parsed.path
        self.old_hosts = set(config.get('previous_domains', []))
        self.config = config
        self.out = Path(destination)
        (self.out / 'assets').mkdir(parents=True, exist_ok=True)
        self.loader = loader
        custom_css = (BASE / 'scripts/mirror.css').read_bytes()
        self.override_css = 'assets/mirror-' + hashlib.sha256(custom_css).hexdigest()[:24] + '.css'
        (self.out / self.override_css).write_bytes(custom_css)
        self.assets = {}
        self.pages = {}
        self.labels = {}

    def page_path(self, url):
        parsed = urlsplit(urljoin(self.source + '/', url))
        if parsed.netloc in self.old_hosts:
            path = parsed.path.strip('/')
        elif parsed.netloc == 'sites.google.com' and (parsed.path == self.prefix or parsed.path.startswith(self.prefix + '/')):
            path = parsed.path[len(self.prefix):].strip('/')
        else:
            return None
        path = unquote(path)
        if any(part in ('..', '.') for part in path.split('/')):
            raise ValueError('Unsafe page path')
        return path

    @staticmethod
    def filename(path):
        return (path or 'index') + '.html'

    def asset(self, url):
        if url.startswith('data:'):
            return url
        if url in self.assets:
            return self.assets[url]
        data, mime, final_url = self.loader(url)
        if mime == 'text/html':
            raise ValueError(f'An asset returned an HTML/login page: {url}')
        if mime == 'text/css':
            def replace(match):
                target = urljoin(final_url, match.group(1))
                local = self.asset(target)
                return 'url(' + (Path(local).name if local.startswith('assets/') else local) + ')'
            data = CSS_URL.sub(replace, data.decode('utf-8')).encode('utf-8')
        suffix = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'text/css': '.css',
                  'font/woff2': '.woff2', 'font/ttf': '.ttf', 'image/svg+xml': '.svg'}.get(mime)
        suffix = suffix or mimetypes.guess_extension(mime) or '.bin'
        local = 'assets/' + hashlib.sha256(data).hexdigest()[:24] + suffix
        (self.out / local).write_bytes(data)
        self.assets[url] = local
        return local

    def discover(self):
        pending = ['']
        while pending:
            path = pending.pop(0)
            if path in self.pages:
                continue
            if len(self.pages) >= 40:
                raise ValueError('More than 40 pages found; review the source site')
            url = self.source + ('/' + quote(path, safe='/') if path else '')
            data, mime, final_url = self.loader(url)
            if self.page_path(final_url) is None:
                raise ValueError('Published source redirected away from Google Sites')
            soup = BeautifulSoup(data, 'html.parser')
            if mime != 'text/html' or not soup.find('section'):
                raise ValueError(f'No published page content at {url}; refusing to deploy')
            self.pages[path] = soup
            for anchor in soup.select('nav a[href]'):
                target = self.page_path(urljoin(url, anchor['href']))
                if target is not None:
                    self.labels.setdefault(target, anchor.get_text(' ', strip=True) or target)
                    if target not in self.pages and target not in pending:
                        pending.append(target)
            # Also include published pages linked within page content (including hidden navigation pages).
            for anchor in soup.select('section a[href]'):
                target = self.page_path(urljoin(url, anchor['href']))
                if target is not None and target not in self.pages and target not in pending:
                    pending.append(target)
        missing = set(self.config.get('required_pages', [])) - set(self.pages)
        if missing:
            raise ValueError(f'Missing required pages: {sorted(missing)}. Review config for intentional removals.')

    def render(self, path, soup):
        prefix = '../' * path.count('/')
        # Fetch short-lived signed image URLs before spending time downloading fonts.
        for image in soup.select('section img[src]'):
            self.asset(urljoin(self.source, image['src']))
        styles = []
        # Keep the published site's favicon and touch icons, with content-based URLs.
        for icon in soup.head.find_all('link', href=True):
            rels = icon.get('rel', [])
            if not set(rels) & {'icon', 'apple-touch-icon', 'apple-touch-icon-precomposed', 'mask-icon'}:
                continue
            local = self.asset(urljoin(self.source, icon['href']))
            attrs = {key: icon[key] for key in ('rel', 'sizes', 'type', 'color') if icon.has_attr(key)}
            attrs['href'] = local if local.startswith('data:') else prefix + local
            attrs = {key: ' '.join(value) if isinstance(value, list) else str(value) for key, value in attrs.items()}
            styles.append('<link ' + ' '.join(key + '="' + html.escape(value, quote=True) + '"' for key, value in attrs.items()) + '>')
        for style in soup.head.find_all('style'):
            css = CSS_URL.sub(lambda m: 'url(' + prefix + self.asset(urljoin(self.source, m.group(1))) + ')', style.get_text())
            styles.append('<style>' + css + '</style>')
        for link in soup.head.select('link[rel="stylesheet"]'):
            local = self.asset(urljoin(self.source, link['href']))
            styles.append('<link rel="stylesheet" href="' + prefix + local + '">')
        content = BeautifulSoup(''.join(str(section) for section in soup.find_all('section')), 'html.parser')
        for tag in content.find_all(['script', 'noscript']):
            tag.decompose()
        for tag in content.select('.PPhIP'):
            tag.decompose()
        for tag in content.find_all(True):
            # Restore lazy iframes before dropping Google application-only attributes.
            if tag.name == 'iframe':
                tag['src'] = tag.get('data-src') or tag.get('src', '')
                if not tag['src'].startswith('https://'):
                    raise ValueError('Unsupported iframe URL')
                tag['title'] = tag.get('aria-label') or 'Embedded content'
                tag['loading'] = 'lazy'
                tag['style'] = 'width:100%;height:80vh;min-height:500px;border:0;'
                fallback = content.new_tag('a', href=tag['src'])
                fallback.string = 'Open ' + tag['title'] + ' in a new tab'
                fallback['target'] = '_blank'; fallback['rel'] = 'noopener'
                tag.insert_after(fallback)
            for attr in list(tag.attrs):
                if attr.startswith(('js', 'data-', 'on')) or attr == 'nonce':
                    del tag[attr]
            if tag.get('role') == 'main':
                del tag['role']
            if tag.has_attr('style') and 'url(' in tag['style']:
                tag['style'] = CSS_URL.sub(lambda m: 'url(' + prefix + self.asset(urljoin(self.source, m.group(1))) + ')', tag['style'])
            if tag.name == 'img':
                tag['src'] = prefix + self.asset(urljoin(self.source, tag['src']))
                tag.attrs.pop('srcset', None)
                tag['loading'] = 'lazy'
                tag['alt'] = tag.get('alt', 'Jun Zhou portrait' if path in ('', 'about') else 'Fieldwork photograph')
            if tag.name == 'a' and tag.get('href'):
                href = tag['href']
                if 'www.google.com/url?' in href:
                    href = parse_qs(urlsplit(href).query).get('q', [href])[0]
                if href.startswith('#'):
                    continue
                absolute = urljoin(self.source + ('/' + path if path else '/'), href)
                target = self.page_path(absolute)
                if target is not None:
                    if target not in self.pages:
                        raise ValueError(f'Unmirrored internal link: {href}')
                    href = prefix + self.filename(target)
                    if urlsplit(absolute).fragment:
                        href += '#' + urlsplit(absolute).fragment
                elif href.startswith('/'):
                    href = absolute
                tag['href'] = href
        nav = ''.join('<a href="' + prefix + html.escape(self.filename(p), quote=True) + '"' +
                      (' aria-current="page"' if p == path or (path == '' and p == 'about') else '') +
                      '>' + html.escape(label) + '</a>' for p, label in self.labels.items())
        title = html.escape((soup.title.get_text() if soup.title else path) + ' · Jun Zhou')
        shell = soup.section.parent.parent.get('class', [])
        body = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{title}</title>' + ''.join(styles) +
                f'<link rel="stylesheet" href="{prefix}{self.override_css}"></head><body>'
                '<a class="skip" href="#main">Skip to content</a><header class="site-header">'
                f'<nav aria-label="Main navigation">{nav}</nav></header>'
                '<main id="main" class="' + html.escape(' '.join(shell), quote=True) + '">'
                '<div class="UtePc RCETm SwuGbc">' + str(content) + '</div></main></body></html>')
        destination = self.out / self.filename(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(body, encoding='utf-8')

    def run(self):
        self.discover()
        for path in self.pages:
            print('Mirroring', path or '(home)', flush=True)
            # Refresh each page just before copying its temporary Google image URLs.
            url = self.source + ('/' + quote(path, safe='/') if path else '')
            data, mime, final_url = self.loader(url + '?mirror_refresh=' + str(time.time_ns()))
            soup = BeautifulSoup(data, 'html.parser')
            if mime != 'text/html' or self.page_path(final_url) != path or not soup.find('section'):
                raise ValueError('Page changed or became inaccessible during synchronization')
            self.render(path, soup)
        (self.out / '.nojekyll').touch()
        # Excludes timestamps and volatile Google image URLs, so equal content has equal digest.
        files = {str(p.relative_to(self.out)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(self.out.rglob('*')) if p.is_file()}
        manifest = {'source': self.source, 'pages': sorted(self.pages), 'files': files}
        (self.out / 'sync-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        validate_site(self.out, self.old_hosts)
        print(f'Validated {len(self.pages)} pages and {len(self.assets)} asset URLs.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=BASE / 'sync-config.json')
    parser.add_argument('--output', type=Path, default=BASE / 'site')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    # Build separately; a failed fetch never replaces the last successful local snapshot.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent, prefix='.sync-') as temp:
        mirror = Mirror(config, temp)
        mirror.run()
        if args.output.exists():
            shutil.rmtree(args.output)
        shutil.copytree(temp, args.output)


if __name__ == '__main__':
    main()
