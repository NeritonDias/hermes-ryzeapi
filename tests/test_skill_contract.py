"""Real Hermes skill loading, without provider traffic or production credentials."""
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1] / 'skills' / 'ryzeapi'


class SkillContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ryze-skill-contract-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        shutil.copytree(SKILL, self.home / 'skills' / 'ryzeapi')
        shutil.copytree(SKILL.parent / 'ryzeapi-painel', self.home / 'skills' / 'ryzeapi-painel')
        self.env = patch.dict(os.environ, {'HERMES_HOME': str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_native_frontmatter_and_lint(self):
        from tools.skill_manager_tool import _validate_frontmatter
        from tools.skill_linter import lint_skill
        from tools.skills_tool_plugin import _safe_frontmatter
        content = (SKILL / 'SKILL.md').read_text()
        self.assertIsNone(_validate_frontmatter(content))
        fm = _safe_frontmatter(content=content)
        self.assertEqual(fm['author'], 'Neriton Dias')
        self.assertLessEqual(len(fm['description']), 60)
        self.assertTrue(fm['description'].endswith('.'))
        findings = lint_skill(SKILL / 'SKILL.md')
        self.assertFalse(findings, repr(findings))
        panel = SKILL.parent / 'ryzeapi-painel' / 'SKILL.md'
        self.assertIsNone(_validate_frontmatter(panel.read_text()))
        self.assertFalse(lint_skill(panel))

    def test_native_channel_visibility(self):
        from agent.prompt_builder import _skill_should_show
        from agent.skill_utils import extract_skill_conditions
        from tools.skills_tool_plugin import _safe_frontmatter
        fm = _safe_frontmatter(content=(SKILL / 'SKILL.md').read_text())
        conditions = extract_skill_conditions(fm)
        for channel in ('cli', 'web', 'desktop', 'ryzeapi', 'whatsapp', 'telegram',
                        'discord', 'slack', 'signal', 'matrix', 'future_channel', ''):
            for toolsets in (set(), {'skills'}, {'skills', 'ryzeapi'}):
                with self.subTest(channel=channel, toolsets=toolsets):
                    self.assertTrue(_skill_should_show(conditions, toolsets, set(), channel))

    def test_native_discovery_and_reference_loading(self):
        from tools import skills_tool as st
        from hermes_cli import plugins
        with patch.object(st, 'SKILLS_DIR', self.home / 'skills'), \
             patch.object(plugins, 'discover_plugins'), \
             patch.object(plugins, 'get_plugin_manager', return_value=plugins.PluginManager()):
            st._SKILLS_CACHE.clear()
            result = json.loads(st.skills_list())
            self.assertTrue(result['success'], result)
            self.assertIn('ryzeapi', [s['name'] for s in result['skills']])
            self.assertIn('ryzeapi-painel', [s['name'] for s in result['skills']])
            self.assertTrue(json.loads(st.skill_view('ryzeapi-painel', preprocess=False))['success'])
            body = json.loads(st.skill_view('ryzeapi', preprocess=False))
            self.assertTrue(body['success'], body)
            self.assertEqual(body['content'], (SKILL / 'SKILL.md').read_text())
            refs = re.findall(r'\]\((references/[^)]+)\)', body['content'])
            self.assertEqual(set(refs), {'references/' + p.name for p in (SKILL / 'references').glob('*.md')})
            for ref in set(refs):
                read = json.loads(st.skill_view('ryzeapi', file_path=ref))
                self.assertTrue(read['success'], read)
                self.assertEqual(read['content'], (SKILL / ref).read_text())
            denied = json.loads(st.skill_view('ryzeapi', file_path='../../settings.json'))
            self.assertFalse(denied['success'])

    def test_native_slash_command(self):
        from agent import skill_commands as sc
        from tools import skills_tool as st
        with patch.object(st, 'SKILLS_DIR', self.home / 'skills'), \
             patch.object(sc, '_skill_commands', {}), \
             patch.object(sc, '_skill_commands_platform', None):
            st._SKILLS_CACHE.clear()
            sc.scan_skill_commands()
            message = sc.build_skill_invocation_message('/ryzeapi', user_instruction='Explique como enviar uma enquete.')
            self.assertIsNotNone(message)
            self.assertIn('Explique como enviar uma enquete.', message)
            panel = sc.build_skill_invocation_message('/ryzeapi-painel', user_instruction='Explique o firewall.')
            self.assertIsNotNone(panel)
            self.assertIn('Explique o firewall.', panel)


if __name__ == '__main__':
    unittest.main()
