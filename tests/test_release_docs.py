"""Release/documentation contracts; no network or provider calls."""
import json
from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
DOCS = ('README.md', 'README.pt-BR.md', 'docs/INSTALL.md', 'docs/INSTALL.pt-BR.md')


class ReleaseDocumentationTests(unittest.TestCase):
    def test_release_versions_match(self):
        version = re.search(r'^version: (.+)$', (ROOT / 'plugin.yaml').read_text(), re.M)[1]
        self.assertRegex(version, r'^\d+\.\d+\.\d+(?:-[a-z]+\.\d+)?$')
        self.assertEqual(json.loads((ROOT / 'dashboard/manifest.json').read_text())['version'], version)
        for name in ('ryzeapi', 'ryzeapi-painel'):
            body = (ROOT / 'skills' / name / 'SKILL.md').read_text()
            self.assertEqual(re.search(r'^version: (.+)$', body, re.M)[1], version)
        for name in DOCS:
            self.assertIn(version, (ROOT / name).read_text())

    def test_language_switches_and_complete_provider_docs(self):
        for name in DOCS:
            body = (ROOT / name).read_text()
            self.assertIn('img.shields.io/badge/Language-English', body)
            self.assertIn('img.shields.io/badge/Idioma-PT--BR', body)
        for name in ('README.md', 'README.pt-BR.md'):
            body = (ROOT / name).read_text()
            self.assertIn('](https://docs.ryzeapi.cloud/)', body)
            self.assertIn('docs/INSTALL', body)

    def test_local_links_and_heading_anchors_resolve(self):
        for name in DOCS:
            document = ROOT / name
            for target in re.findall(r'\]\(([^)\s]+)\)', document.read_text()):
                link = urlsplit(target)
                if link.scheme or link.netloc:
                    continue
                resolved = document.parent / unquote(link.path) if link.path else document
                self.assertTrue(resolved.is_file(), f'{name}: missing {target}')
                if link.fragment:
                    headings = re.findall(r'^#+\s+(.+)$', resolved.read_text(), re.M)
                    anchors = [re.sub(r'[^\w\- ]', '', title.lower()).replace(' ', '-') for title in headings]
                    self.assertIn(unquote(link.fragment), anchors, f'{name}: missing anchor {target}')

    def test_tutorials_cover_install_and_both_skills(self):
        for name in ('docs/INSTALL.md', 'docs/INSTALL.pt-BR.md'):
            body = (ROOT / name).read_text()
            self.assertLess(body.index('python -m pip install'), body.index('hermes plugins enable'))
            for contract in ('ryzeapi-painel', 'scripts/verify_install.py', '/ryzeapi/events',
                             '--check', 'WHATSAPP_ENABLED=false', 'hermes plugins uninstall'):
                self.assertIn(contract, body)
