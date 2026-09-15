"""Bounded retention of this plugin's generated media only; never follow symlinks."""
import re
import time

CACHE_TTL = 86400
CACHE_LIMIT = 256 * 1024 * 1024

def clean_media_cache(directory, *, now=None):
    now = time.time() if now is None else now
    if not directory.exists() or directory.is_symlink(): return 0
    files = []
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file(): continue
        if not re.fullmatch(r'[a-f0-9]{64}\.[a-zA-Z0-9]{1,11}', path.name): continue
        stat = path.stat()
        files.append((stat.st_mtime, stat.st_size, path))
    total = sum(size for _, size, _ in files)
    removed = 0
    for modified, size, path in sorted(files):
        # Never evict fresh files for capacity; running jobs may still use them.
        if now-modified > CACHE_TTL or (total > CACHE_LIMIT and now-modified > 3600):
            path.unlink()
            total -= size
            removed += 1
    return removed
