"""Check installed native discovery and both skills; does not contact RyzeAPI."""
import json
from pathlib import Path
from hermes_constants import get_hermes_home
from hermes_cli.plugins import discover_plugins, get_plugin_manager
from tools.skills_tool import skills_list, skill_view

discover_plugins()
manager = get_plugin_manager()
names = {item['name'] for item in json.loads(skills_list())['skills']}
checks = {}
for name in ('ryzeapi', 'ryzeapi-painel'):
    checks[name] = {
        'installed': (get_hermes_home() / 'skills' / name / 'SKILL.md').is_file(),
        'listed': name in names,
        'readable': json.loads(skill_view(name, preprocess=False)).get('success') is True,
        'bundled_readable': json.loads(skill_view('ryzeapi:' + name, preprocess=False)).get('success') is True,
    }
passed = all(all(value.values()) for value in checks.values())
print(json.dumps({'success': passed, 'skills': checks, 'provider_calls': 0}, ensure_ascii=False))
raise SystemExit(0 if passed else 1)
