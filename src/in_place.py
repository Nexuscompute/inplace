"""
In-place file processing

The ``in_place`` module provides an ``InPlace`` class for reading & writing a
file "in-place": data that you write ends up at the same filepath that you read
from, and ``in_place`` takes care of all the necessary mucking about with
temporary files for you.

Visit <https://github.com/jwodder/inplace> for more information.
"""

__version__ = "1.0.0.dev1"
__author__ = "John Thorvald Wodder II"
__author_email__ = "inplace@varonathe.org"
__license__ = "MIT"
__url__ = "https://github.com/jwodder/inplace"

import os
import os.path
import shutil
import tempfile
from warnings import warn

__all__ = ["InPlace", "InPlaceBytes", "InPlaceText"]


class InPlace:
    """
    A class for reading from & writing to a file "in-place" (with data that you
    write ending up at the same filepath that you read from) that takes care of
    all the necessary mucking about with temporary files.

    :param name: The path to the file to open & edit in-place (resolved
        relative to the current directory at the time of the instance's
        creation)
    :type name: path-like

    :param string mode: Whether to operate on the file in binary or text mode.
        If ``mode`` is ``'b'``, the file will be opened in binary mode, and
        data will be read & written as `bytes` objects.  If ``mode`` is ``'t'``
        or unset, the file will be opened in text mode, and data will be read &
        written as `str` objects.

    :param backup: The path at which to save the file's original contents once
        editing has finished (resolved relative to the current directory at the
        time of the instance's creation); if `None` (the default), no backup is
        saved
    :type backup: path-like

    :param backup_ext: A string to append to ``name`` to get the path at which
        to save the file's original contents.  Cannot be empty.  ``backup`` and
        ``backup_ext`` are mutually exclusive.
    :type backup_ext: path-like

    :param kwargs: Additional keyword arguments to pass to `open()`
    """

    def __init__(
        self,
        name,
        mode=None,
        backup=None,
        backup_ext=None,
        **kwargs,
    ):
        cwd = os.getcwd()
        #: The path to the file to edit in-place
        self.name = os.fsdecode(name)
        #: Whether to operate on the file in binary or text mode
        self.mode = mode
        #: The absolute path of the file to edit in-place
        self.filepath = os.path.join(cwd, self.name)
        #: ``filepath`` with symbolic links resolved
        self.realpath = os.path.realpath(self.filepath)
        if backup is not None:
            if backup_ext is not None:
                raise ValueError("backup and backup_ext are mutually exclusive")
            #: The absolute path of the backup file (if any) that the original
            #: contents of ``realpath`` will be moved to after editing
            self.backuppath = os.path.join(cwd, os.fsdecode(backup))
        elif backup_ext is not None:
            if not backup_ext:
                raise ValueError("backup_ext cannot be empty")
            self.backuppath = self.realpath + os.fsdecode(backup_ext)
        else:
            self.backuppath = None
        #: Additional arguments to pass to `open`
        self.kwargs = kwargs
        #: The input filehandle from which data is read; only non-`None` while
        #: the instance is open
        self.input = None
        #: The output filehandle to which data is written; only non-`None`
        #: while the instance is open
        self.output = None
        #: The absolute path to the temporary file; only non-`None` while the
        #: instance is open
        self._tmppath = None
        #: `True` iff the filehandle is not currently open
        self.closed = False
        try:
            self._tmppath = self._mktemp(self.realpath)
            self.output = self.open_write(self._tmppath)
            copystats(self.realpath, self._tmppath)
            input_path = self.realpath
            self.input = self.open_read(input_path)
        except Exception:
            self.rollback()
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc_value, _traceback):
        if not self.closed:
            if exc_type is not None:
                self.rollback()
            else:
                self.close()
        return False

    def _mktemp(self, filepath):
        """
        Create an empty temporary file in the same directory as ``filepath``
        and return the path to the new file
        """
        fd, tmppath = tempfile.mkstemp(
            dir=os.path.dirname(filepath),
            prefix="._in_place-",
        )
        os.close(fd)
        return tmppath

    def open_read(self, path):
        """
        Open the file at ``path`` for reading and return a file-like object.
        Use :attr:`mode` to determine whether to open in binary or text mode.
        """
        if not self.mode or self.mode == "t":
            return open(path, "r", **self.kwargs)
        elif self.mode == "b":
            return open(path, "rb", **self.kwargs)
        else:
            raise ValueError(f"{self.mode!r}: invalid mode")

    def open_write(self, path):
        """
        Open the file at ``path`` for writing and return a file-like object.
        Use :attr:`mode` to determine whether to open in binary or text mode.
        """
        if not self.mode or self.mode == "t":
            return open(path, "w", **self.kwargs)
        elif self.mode == "b":
            return open(path, "wb", **self.kwargs)
        else:
            raise ValueError(f"{self.mode!r}: invalid mode")

    def _close(self):
        """
        Close filehandles (if they aren't closed already) and set them to
        `None`
        """
        self.closed = True
        if self.input is not None:
            self.input.close()
            self.input = None
        if self.output is not None:
            self.output.close()
            self.output = None

    def close(self):
        """
        Close filehandles and move affected files to their final destinations.
        If called after the filehandle has already been closed (with either
        this method or :meth:`rollback`), :meth:`close` does nothing.

        :return: `None`
        """
        if not self.closed:
            self._close()
            try:
                if self.backuppath is not None:
                    os.replace(self.realpath, self.backuppath)
                os.replace(self._tmppath, self.realpath)
            finally:
                if self._tmppath is not None:
                    try_unlink(self._tmppath)
                    self._tmppath = None

    def rollback(self):
        """
        Close filehandles and remove/rename temporary files so that things look
        like they did before the `InPlace` instance was opened

        :return: `None`
        :raises ValueError: if called after the `InPlace` instance is closed
        """
        if not self.closed:
            self._close()
            if self._tmppath is not None:  # In case of error while opening
                try_unlink(self._tmppath)
                self._tmppath = None
        else:
            raise ValueError("Cannot rollback closed file")

    def read(self, size=-1):
        if self.closed:
            raise ValueError("Filehandle is not currently open")
        return self.input.read(size)

    def readline(self, size=-1):
        if self.closed:
            raise ValueError("Filehandle is not currently open")
        return self.input.readline(size)

    def readlines(self, sizehint=-1):
        if self.closed:
            raise ValueError("Filehandle is not currently open")
        return self.input.readlines(sizehint)

    def readinto(self, b):
        if self.closed:
            raise ValueError("Filehandle is not currently open")
        return self.input.readinto(b)

    def write(self, s):
        if self.closed:
            raise ValueError("Filehandle is not currently open")
        self.output.write(s)

    def writelines(self, seq):
        if self.closed:
            raise ValueError("Filehandle is not currently open")
        self.output.writelines(seq)

    def __iter__(self):
        if self.closed:
            raise ValueError("Filehandle is not currently open")
        return iter(self.input)

    def flush(self):
        if self.closed:
            raise ValueError("Filehandle is not currently open")
        self.output.flush()


class InPlaceBytes(InPlace):
    """Deprecated.  Please use `InPlace` with ``mode='b'`` instead."""

    def __init__(self, name, **kwargs):
        warn(
            "InPlaceBytes is deprecated."
            '  Please use `InPlace(name, mode="b")` instead.',
            DeprecationWarning,
        )
        super(InPlaceBytes, self).__init__(name, mode="b", **kwargs)


class InPlaceText(InPlace):
    """Deprecated.  Please use `InPlace` with ``mode='t'`` instead."""

    def __init__(self, name, **kwargs):
        warn(
            "InPlaceText is deprecated."
            '  Please use `InPlace(name, mode="t")` instead.',
            DeprecationWarning,
        )
        super(InPlaceText, self).__init__(name, mode="t", **kwargs)


def copystats(from_file, to_file):
    """
    Copy stat info from ``from_file`` to ``to_file`` using `shutil.copystat`.
    If possible, also copy the user and/or group ownership information.
    """
    shutil.copystat(from_file, to_file)
    if hasattr(os, "chown"):
        st = os.stat(from_file)
        # Based on GNU sed's behavior:
        try:
            os.chown(to_file, st.st_uid, st.st_gid)
        except IOError:
            try:
                os.chown(to_file, -1, st.st_gid)
            except IOError:
                pass


def try_unlink(path):
    """
    Try to delete the file at ``path``.  If the file doesn't exist, do nothing;
    any other errors are propagated to the caller.
    """
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
