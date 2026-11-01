"""Fail closed on missing resources, unsafe output, or corrupted saved artifacts."""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit
from bs4 import BeautifulSoup

CSS_URL = re.compile(r'url\(\s*[\"\']?([^\)\"\']+)[\"\']?\s*\)')


def validate_inventory(directory):
    root = Path(directory)
    paths = list(root.rglob('*'))
    if any(p.is_symlink() for p in paths):
        raise ValueError('Website must not contain symbolic links')
    if not (root / 'index.html').is_file():
        raise ValueError('Missing website entry point')
    manifest_path = root / 'sync-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    files = manifest.get('files')
    if not isinstance(files, dict):
        raise ValueError('Invalid manifest inventory')
    actual = {str(p.relative_to(root)) for p in paths if p.is_file() and p != manifest_path}
    if actual != set(files):
        raise ValueError('Manifest file inventory does not match website')
    for name, expected in files.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or any(part.startswith('.') for part in relative.parts if name != '.nojekyll'):
            raise ValueError('Unsafe manifest path')
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError('Unsafe manifest path')
        if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError('Invalid checksum')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'File checksum mismatch: {name}')
    return manifest


def local_target(root, page, url):
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    relative = unquote(parsed.path)
    target = ((root / relative.lstrip('/')) if relative.startswith('/') else (page.parent / relative)).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f'Local reference escapes website: {url}')
    if not target.is_file():
        raise ValueError(f'Missing local resource: {page.name}: {url}')
    return target


def validate_site(directory, previous_domains=()):
    root = Path(directory)
    manifest = validate_inventory(root)
    files = [p for p in root.rglob('*') if p.is_file()]
    for page in root.rglob('*.html'):
        soup = BeautifulSoup(page.read_text(), 'html.parser')
        if soup.find(['script', 'base', 'object', 'embed', 'form']):
            raise ValueError(f'Unsupported active HTML in {page.name}')
        for tag in soup.find_all(True):
            if any(attr.lower().startswith('on') for attr in tag.attrs):
                raise ValueError('Inline event handler survived conversion')
            if tag.has_attr('srcdoc'):
                raise ValueError('Inline iframe HTML is not allowed')
            for attr in ('href', 'src', 'xlink:href', 'action', 'formaction'):
                if not tag.has_attr(attr):
                    continue
                url = str(tag[attr]).strip()
                scheme = urlsplit(url).scheme.lower()
                if scheme not in ('', 'https', 'http', 'mailto', 'tel', 'data'):
                    raise ValueError(f'Unsafe URL scheme: {scheme}')
                if scheme == 'data' and not (tag.name in ('img', 'link') and url.startswith('data:image/')):
                    raise ValueError('Unsupported data URL')
                if urlsplit(url).hostname in previous_domains:
                    raise ValueError('Reference to retired domain')
                if (tag.name == 'img' or (tag.name == 'link' and set(tag.get('rel', [])) & {'stylesheet', 'icon'})) and (urlsplit(url).scheme in ('http', 'https') or urlsplit(url).netloc):
                    raise ValueError('Image, icon or stylesheet was not copied locally')
                local_target(root, page, url)
            if tag.name == 'iframe' and urlsplit(tag.get('src', '')).scheme != 'https':
                raise ValueError('Embedded content must use HTTPS')
    for css in root.rglob('*.css'):
        if re.search(r'@import\s', css.read_text(), re.I):
            raise ValueError('CSS imports require explicit conversion')
        for match in CSS_URL.finditer(css.read_text()):
            url = match.group(1)
            if url.startswith('data:'):
                continue
            if urlsplit(url).scheme or urlsplit(url).netloc:
                raise ValueError('A CSS resource was not copied locally')
            local_target(root, css, url)
    return {'pages': len(list(root.rglob('*.html'))), 'files': len(files)}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_site(args.directory)))
