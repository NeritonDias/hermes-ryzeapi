"""Read approved attachments relative to the active profile, without following links."""
import os
import stat
from pathlib import Path

from hermes_constants import get_hermes_home
from .core import MAX_MEDIA


def attachment_root():
    return get_hermes_home() / 'workspace' / 'attachments'


def read_attachment(path):
    root = attachment_root()
    path = Path(path)
    if path.is_absolute():
        try:
            path = path.relative_to(root)
        except ValueError:
            raise ValueError('Choose a file in workspace/attachments') from None
    if not path.parts or '..' in path.parts:
        raise ValueError('Invalid attachment path')
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(root.parent.parent, directory_flags)
    try:
        for part in ('workspace', 'attachments', *path.parts[:-1]):
            child = os.open(part, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= MAX_MEDIA:
                raise ValueError('Choose a regular attachment of at most 8 MiB')
            data = stream.read(MAX_MEDIA + 1)
            if not 0 < len(data) <= MAX_MEDIA:
                raise ValueError('Invalid attachment size')
            return data
    finally:
        os.close(directory)
