import errno
import os
from pathlib import Path
import stat
import struct

import pytest
from deploy.prepare_image import normalize


def acl(entries):
    return struct.pack('<I', 2) + b''.join(struct.pack('<HHI', *entry) for entry in entries)


def test_normalize_modes_and_preserve_content(tmp_path):
    directory = tmp_path / 'src'
    directory.mkdir(mode=0o700)
    file = directory / '__init__.py'
    file.write_text('# application\n')
    file.chmod(0o600)
    normalize(tmp_path)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o755
    assert stat.S_IMODE(file.stat().st_mode) == 0o644
    assert file.read_text() == '# application\n'


def test_remove_named_user_deny_and_directory_default(tmp_path):
    file = tmp_path / '__init__.py'
    file.write_text('# application\n')
    # User 10001 is explicitly denied, despite the readable mask/other bits.
    value = acl([(1, 7, 0xffffffff), (2, 0, 10001), (4, 5, 0xffffffff),
                 (16, 5, 0xffffffff), (32, 5, 0xffffffff)])
    try:
        os.setxattr(file, 'system.posix_acl_access', value)
        os.setxattr(tmp_path, 'system.posix_acl_default', value)
    except OSError as error:
        if error.errno in (errno.ENOTSUP, errno.EOPNOTSUPP, errno.EINVAL):
            pytest.skip('Test filesystem does not support POSIX ACL fixtures')
        raise
    file.chmod(0o644)
    assert 'system.posix_acl_access' in os.listxattr(file)
    normalize(tmp_path)
    assert 'system.posix_acl_access' not in os.listxattr(file)
    assert 'system.posix_acl_default' not in os.listxattr(tmp_path)
    assert stat.S_IMODE(file.stat().st_mode) == 0o644


def test_symlink_cannot_change_files_outside_image_root(tmp_path):
    outside = tmp_path / 'outside'
    outside.write_text('unchanged')
    outside.chmod(0o600)
    root = tmp_path / 'image'
    root.mkdir()
    (root / 'link').symlink_to(outside)
    with pytest.raises(ValueError, match='non-regular'):
        normalize(root)
    assert stat.S_IMODE(outside.stat().st_mode) == 0o600
