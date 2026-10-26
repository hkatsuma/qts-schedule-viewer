"""Normalize image-owned application files, including inherited POSIX ACLs.

Run as root during Docker build only. Never pass a host configuration mount.
"""
import errno
import os
from pathlib import Path
import stat
import sys

ACL_ATTRIBUTES = {'system.posix_acl_access', 'system.posix_acl_default'}


def normalize(path: Path) -> None:
    mode = path.lstat().st_mode
    if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
        raise ValueError(f'Image context contains a non-regular entry: {path}')
    try:
        attributes = os.listxattr(path)
    except OSError as error:
        if error.errno not in (errno.ENOTSUP, errno.EOPNOTSUPP):
            raise
        attributes = []
    # chmod updates the ACL mask, but does not remove named-user deny entries.
    # Remove access ACLs and directory defaults before setting ordinary modes.
    for attribute in ACL_ATTRIBUTES.intersection(attributes):
        os.removexattr(path, attribute)
    os.chmod(path, 0o755 if stat.S_ISDIR(mode) else 0o644)
    if stat.S_ISDIR(mode):
        for child in path.iterdir():
            normalize(child)


if __name__ == '__main__':
    root = Path(sys.argv[1])
    if root != Path('/app'):
        raise SystemExit('This build helper only accepts /app')
    normalize(root)
    print('Image application modes normalized; inherited POSIX access/default ACLs removed')
