"""Run the backend suite against an existing Hermes source tree, in an isolated home."""
import os,subprocess,sys,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
source=os.environ.get('HERMES_SOURCE')
if not source or not (Path(source)/'hermes_constants.py').exists():
    raise SystemExit('Set HERMES_SOURCE to the Hermes checkout; use its Python environment.')
with tempfile.TemporaryDirectory(prefix='ryzeapi-tests-') as home:
    env=dict(os.environ,HERMES_HOME=home,
             PYTHONPATH=str(root/'tests')+os.pathsep+source,HERMES_SOURCE=source)
    for key in list(env):
        if key.startswith('RYZEAPI_'):env.pop(key)
    # Browser suites are explicit entrypoints, not unittest cases; keep their
    # optional Playwright dependency out of a backend-only clean installation.
    modules=[p.stem for p in sorted((root/'tests').glob('test_*.py'))
             if not p.name.startswith('test_ui')]
    raise SystemExit(subprocess.call([sys.executable,'-m','unittest','-q',*modules],env=env,cwd=home))
