"""Expose both bundled skills in the active profile without overwriting local edits."""
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
import time

log = logging.getLogger(__name__)
SKILLS = ('ryzeapi', 'ryzeapi-painel')


def hashes(folder):
    if folder.is_symlink():
        raise ValueError('Symlink skill directory')
    result = {}
    for path in sorted(folder.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlink inside skill')
        if path.is_file():
            result[str(path.relative_to(folder))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def install_skills(home=None, source=None):
    from hermes_constants import get_hermes_home
    home = Path(home or get_hermes_home()).resolve()
    source = Path(source or Path(__file__).parent / 'skills')
    root, data = home / 'skills', home / 'ryzeapi'
    if root.is_symlink() or data.is_symlink():
        raise ValueError('Refusing symlinked skill/data root')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path, state_path = data / 'skill-install.lock', data / 'skill-install.json'
    if lock_path.is_symlink() or state_path.is_symlink():
        raise ValueError('Refusing symlinked skill ownership files')
    with lock_path.open('a') as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        if not isinstance(state, dict):
            raise ValueError('Invalid skill ownership manifest')
        outcomes = {}
        for name in SKILLS:
            shipped, target = source / name, root / name
            expected = hashes(shipped)
            if 'SKILL.md' not in expected:
                raise ValueError('Missing bundled skill')
            if target.is_symlink() or (target.exists() and not target.is_dir()):
                outcomes[name] = 'conflict'
                continue
            current = hashes(target) if target.exists() else None
            if current == expected:
                state[name] = expected
                outcomes[name] = 'unchanged'
                continue
            if current is not None and current != state.get(name):
                outcomes[name] = 'conflict'
                continue
            temporary = Path(tempfile.mkdtemp(prefix='.ryze-skill-', dir=root))
            backup = None
            try:
                for relative in expected:
                    path = temporary / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(shipped / relative, path)
                    path.chmod(0o600)
                if hashes(temporary) != expected:
                    raise ValueError('Skill copy verification failed')
                if current is not None:
                    backups = data / 'skill-backups'
                    if backups.is_symlink():
                        raise ValueError('Refusing symlinked backup directory')
                    backups.mkdir(exist_ok=True, mode=0o700)
                    backup = backups / (name + '-' + str(time.time_ns()))
                    os.replace(target, backup)
                try:
                    os.replace(temporary, target)
                except BaseException:
                    if backup is not None:
                        os.replace(backup, target)
                    raise
                state[name] = expected
                outcomes[name] = 'installed' if current is None else 'updated'
            finally:
                # Only the exact temporary directory created by this call.
                if temporary.exists():
                    shutil.rmtree(temporary)
        fd, temp = tempfile.mkstemp(prefix='.skill-install-', dir=data)
        try:
            with os.fdopen(fd, 'w') as output:
                json.dump(state, output, sort_keys=True)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp, state_path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return outcomes


def register_skills(ctx):
    root = Path(__file__).parent / 'skills'
    if hasattr(ctx, 'register_skill'):
        for name in SKILLS:
            ctx.register_skill(name, root / name / 'SKILL.md')
    try:
        for name, status in install_skills().items():
            if status == 'conflict':
                log.warning('RyzeAPI skill %s preserved: local copy differs; use ryzeapi:%s or review the conflict.', name, name)
    except (OSError, ValueError, TypeError):
        log.warning('RyzeAPI automatic skill installation unavailable; bundled namespaced skills remain available.')
