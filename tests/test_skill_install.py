import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ryze_skill_installer_test', ROOT / 'skill_install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallSkillTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='ryze-install-test-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.home = self.root / 'profile'
        self.source = self.root / 'source'
        shutil.copytree(ROOT / 'skills', self.source)

    def run_install(self):
        return installer.install_skills(self.home, self.source)

    def test_both_skills_installed_and_idempotent(self):
        self.assertEqual(set(self.run_install().values()), {'installed'})
        before = {name: (self.home / 'skills' / name / 'SKILL.md').stat().st_mtime_ns for name in installer.SKILLS}
        self.assertEqual(set(self.run_install().values()), {'unchanged'})
        for name in installer.SKILLS:
            self.assertEqual(installer.hashes(self.source / name), installer.hashes(self.home / 'skills' / name))
            self.assertEqual(before[name], (self.home / 'skills' / name / 'SKILL.md').stat().st_mtime_ns)
        self.assertEqual((self.home / 'ryzeapi/skill-install.json').stat().st_mode & 0o777, 0o600)

    def test_managed_update_and_backup(self):
        self.run_install()
        file = self.source / 'ryzeapi/SKILL.md'
        previous = file.read_text()
        file.write_text(previous + '\nNew release instructions.\n')
        self.assertEqual(self.run_install()['ryzeapi'], 'updated')
        backups = list((self.home / 'ryzeapi/skill-backups').glob('ryzeapi-*/SKILL.md'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), previous)

    def test_local_edits_and_other_author_preserved(self):
        self.run_install()
        file = self.home / 'skills/ryzeapi/SKILL.md'
        file.write_text('My personal instructions')
        self.assertEqual(self.run_install()['ryzeapi'], 'conflict')
        self.assertEqual(file.read_text(), 'My personal instructions')
        (self.home / 'ryzeapi/skill-install.json').unlink()
        self.assertEqual(self.run_install()['ryzeapi'], 'conflict')
        self.assertEqual(file.read_text(), 'My personal instructions')

    def test_extra_user_reference_preserved(self):
        self.run_install()
        file = self.home / 'skills/ryzeapi/references/personal.md'
        file.write_text('Personal note')
        self.assertEqual(self.run_install()['ryzeapi'], 'conflict')
        self.assertEqual(file.read_text(), 'Personal note')

    def test_symlinks_rejected(self):
        self.home.mkdir()
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        (self.home / 'skills').symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.run_install()
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_failed_update_restores_previous(self):
        self.run_install()
        file = self.source / 'ryzeapi/SKILL.md'
        previous = file.read_bytes()
        file.write_bytes(previous + b'\nUpdated\n')
        replace = installer.os.replace
        def fail_once(source, destination):
            if Path(source).name.startswith('.ryze-skill-'):
                raise OSError('Synthetic failure')
            return replace(source, destination)
        with patch.object(installer.os, 'replace', side_effect=fail_once):
            with self.assertRaises(OSError):
                self.run_install()
        self.assertEqual((self.home / 'skills/ryzeapi/SKILL.md').read_bytes(), previous)

    def test_registers_both_namespaced_skills_and_installs(self):
        calls = []
        class Context:
            def register_skill(self, name, path):
                calls.append((name, path.is_file()))
        with patch('hermes_constants.get_hermes_home', return_value=self.home):
            installer.register_skills(Context())
        self.assertEqual(calls, [(name, True) for name in installer.SKILLS])
        self.assertTrue((self.home / 'skills/ryzeapi-painel/SKILL.md').is_file())


if __name__ == '__main__':
    unittest.main()
