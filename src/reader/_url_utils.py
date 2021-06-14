"""
URL and path utilities. Contains no business logic.

In this context, bare paths are considered equivalent to file:// URIs.

"""
import os.path
from urllib.parse import urlparse
from urllib.parse import urlunparse

# for url2pathname, but we want to allow it to be monkeypatched during testing
import urllib.request  # noreorder


def normalize_url(url: str) -> str:
    """Return a consistent version of `url`.

    Currently, this only covers minor differences.
    Notably, the scheme and path are left unchanged.

    >>> normalize_url('one')
    'one'
    >>> normalize_url('one?')
    'one'
    >>> normalize_url('file:two')
    'file:///two'
    >>> normalize_url('file:///two')
    'file:///two'

    """
    return urlunparse(urlparse(url))


def extract_path(url: str) -> str:
    """Transform a file URI or a path to a path."""

    url_parsed = urlparse(url)

    if url_parsed.scheme == 'file':
        if url_parsed.netloc not in ('', 'localhost'):
            raise ValueError("unknown authority for file URI")
        # TODO: maybe disallow query, params, fragment too, to reserve for future uses

        return urllib.request.url2pathname(url_parsed.path)

    if url_parsed.scheme:
        # on Windows, drive is the drive letter or UNC \\host\share;
        # on POSIX, drive is always empty
        drive, _ = os.path.splitdrive(url)

        if not drive:
            # should end up as the same type as "no parsers were found", maybe
            raise ValueError("unknown scheme for file URI")

        # we have a scheme, but we're on Windows and url looks like a path
        return url

    # no scheme, treat as a path
    return url


def resolve_root(root: str, path: str) -> str:
    """Resolve a path relative to a root, and normalize the result.

    This is a path computation, there's no checks perfomed on the arguments.

    It works like os.normcase(os.path.normpath(os.path.join(root, path))),
    but with additional restrictions:

    * root must be absolute.
    * path must be relative.
    * Directory traversal above the root is not allowed;
      https://en.wikipedia.org/wiki/Directory_traversal_attack

    Symlinks are allowed, as long as they're under the root.

    Note that the '..' components are collapsed with no regard for symlinks.

    """

    # this implementation is based on the requirements / notes in
    # https://github.com/lemon24/reader/issues/155#issuecomment-672324186

    if not is_abs_path(root):
        raise ValueError(f"root must be absolute: {root!r}")
    if not is_rel_path(path):
        raise ValueError(f"path must be relative: {path!r}")

    root = os.path.normcase(os.path.normpath(root))

    # we normalize the path **before** symlinks are resolved;
    # i.e. it behaves as realpath -L (logical), not realpath -P (physical).
    # https://docs.python.org/3/library/os.path.html#os.path.normpath
    # https://stackoverflow.com/questions/34865153/os-path-normpath-and-symbolic-links
    path = os.path.normcase(os.path.normpath(os.path.join(root, path)))

    # this means we support symlinks, as long as they're under the root
    # (the target itself may be outside).

    # if we want to prevent symlink targets outside root,
    # we should do it here.

    if not path.startswith(root):
        raise ValueError(f"path cannot be outside root: {path!r}")

    return path


def is_abs_path(path: str) -> bool:
    """Return True if path is an absolute pathname.

    Unlike os.path.isabs(), return False on Windows if there's no drive
    (e.g. "\\path").

    """
    is_abs = os.path.isabs(path)
    has_drive = os.name != 'nt' or os.path.splitdrive(path)[0]
    return all([is_abs, has_drive])


def is_rel_path(path: str) -> bool:
    """Return True if path is a relative pathname.

    Unlike "not os.path.isabs()", return False on windows if there's a drive
    (e.g. "C:path").

    """
    is_abs = os.path.isabs(path)
    has_drive = os.name == 'nt' and os.path.splitdrive(path)[0]
    return not any([is_abs, has_drive])


# TODO: pathlib.PurePath.is_reserved does the same thing, get rid of this?


def is_windows_device_file(path: str) -> bool:
    if os.name != 'nt':
        return False
    filename = os.path.basename(os.path.normpath(path)).upper()
    return filename in _windows_device_files


# from werkzeug.utils
_windows_device_files = (
    "CON",
    "AUX",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "LPT1",
    "LPT2",
    "LPT3",
    "PRN",
    "NUL",
)
