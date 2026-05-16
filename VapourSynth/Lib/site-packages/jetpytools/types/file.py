from __future__ import annotations

from os import X_OK, PathLike, access, listdir, path, walk
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Literal, Self, TypeAlias

__all__ = [
    "FileDescriptor",
    "FilePathType",
    "OpenBinaryMode",
    "OpenBinaryModeReading",
    "OpenBinaryModeUpdating",
    "OpenBinaryModeWriting",
    "OpenTextMode",
    "OpenTextModeReading",
    "OpenTextModeUpdating",
    "OpenTextModeWriting",
    "SPath",
    "SPathLike",
]


FileDescriptor: TypeAlias = int

FilePathType: TypeAlias = str | bytes | PathLike[str] | PathLike[bytes]

OpenTextModeUpdating: TypeAlias = Literal[
    "r+",
    "+r",
    "rt+",
    "r+t",
    "+rt",
    "tr+",
    "t+r",
    "+tr",
    "w+",
    "+w",
    "wt+",
    "w+t",
    "+wt",
    "tw+",
    "t+w",
    "+tw",
    "a+",
    "+a",
    "at+",
    "a+t",
    "+at",
    "ta+",
    "t+a",
    "+ta",
    "x+",
    "+x",
    "xt+",
    "x+t",
    "+xt",
    "tx+",
    "t+x",
    "+tx",
]
OpenTextModeWriting: TypeAlias = Literal["w", "wt", "tw", "a", "at", "ta", "x", "xt", "tx"]
OpenTextModeReading: TypeAlias = Literal["r", "rt", "tr", "U", "rU", "Ur", "rtU", "rUt", "Urt", "trU", "tUr", "Utr"]

OpenBinaryModeUpdating: TypeAlias = Literal[
    "rb+",
    "r+b",
    "+rb",
    "br+",
    "b+r",
    "+br",
    "wb+",
    "w+b",
    "+wb",
    "bw+",
    "b+w",
    "+bw",
    "ab+",
    "a+b",
    "+ab",
    "ba+",
    "b+a",
    "+ba",
    "xb+",
    "x+b",
    "+xb",
    "bx+",
    "b+x",
    "+bx",
]
OpenBinaryModeWriting: TypeAlias = Literal["wb", "bw", "ab", "ba", "xb", "bx"]
OpenBinaryModeReading: TypeAlias = Literal["rb", "br", "rbU", "rUb", "Urb", "brU", "bUr", "Ubr"]

OpenTextMode: TypeAlias = OpenTextModeUpdating | OpenTextModeWriting | OpenTextModeReading
OpenBinaryMode: TypeAlias = OpenBinaryModeUpdating | OpenBinaryModeReading | OpenBinaryModeWriting


class SPath(Path):
    """Modified version of pathlib.Path"""

    if TYPE_CHECKING:

        def __new__(cls, *args: SPathLike, **kwargs: Any) -> Self: ...

    def format(self, *args: Any, **kwargs: Any) -> SPath:
        """Format the path with the given arguments."""

        return SPath(self.to_str().format(*args, **kwargs))

    def to_str(self) -> str:
        """Cast the path to a string."""

        return str(self)

    def get_folder(self) -> SPath:
        """Get the folder of the path."""

        folder_path = self.resolve()

        if folder_path.is_dir():
            return folder_path

        return SPath(path.dirname(folder_path))

    def mkdirp(self, mode: int = 0o777) -> None:
        """Make the dir path with its parents."""

        return self.get_folder().mkdir(mode, True, True)

    def rmdirs(self, missing_ok: bool = False, ignore_errors: bool = True) -> None:
        """Remove the dir path with its contents."""

        import shutil

        try:
            return shutil.rmtree(self.get_folder(), ignore_errors)
        except FileNotFoundError:
            if not missing_ok:
                raise

    def read_lines(self, encoding: str | None = None, errors: str | None = None, keepends: bool = False) -> list[str]:
        """Read the file and return its lines."""

        return super().read_text(encoding, errors).splitlines(keepends)

    def write_lines(
        self, data: Iterable[str], encoding: str | None = None, errors: str | None = None, newline: str | None = None
    ) -> int:
        """Open the file and write the given lines."""

        return super().write_text("\n".join(data), encoding, errors, newline)

    def append_to_stem(self, suffixes: str | Iterable[str], sep: str = "_") -> SPath:
        """Append a suffix to the stem of the path"""

        from ..functions import to_arr

        return self.with_stem(sep.join([self.stem, *to_arr(suffixes)]))

    def is_empty_dir(self) -> bool:
        """Check if the directory is empty."""

        return self.is_dir() and not any(self.iterdir())

    def move_dir(self, dst: SPathLike, *, mode: int = 0o777) -> None:
        """Move the directory to the specified destination."""

        dst = SPath(dst)

        dst.mkdir(mode, True, True)

        for file in listdir(self):
            src_file = self / file
            dst_file = dst / file

            if dst_file.exists():
                src_file.unlink()
            else:
                src_file.rename(dst_file)

        self.rmdir()

    def copy_dir(self, dst: SPathLike) -> SPath:
        """Copy the directory to the specified destination."""
        import shutil

        if not self.is_dir():
            from ..exceptions import PathIsNotADirectoryError

            raise PathIsNotADirectoryError('The given path, "{self}" is not a directory!', self.copy_dir)

        dst = SPath(dst)

        dst.mkdirp()

        shutil.copytree(self, dst, dirs_exist_ok=True)

        return dst

    def lglob(self, pattern: str = "*") -> list[SPath]:
        """Glob the path and return the list of paths."""

        return list(map(SPath, self.glob(pattern)))

    def fglob(self, pattern: str = "*") -> SPath | None:
        """Glob the path and return the first match."""
        import fnmatch

        for root, dirs, files in walk(self):
            for name in dirs + files:
                if fnmatch.fnmatch(name, pattern):
                    return SPath(path.join(root, name))

        return None

    def find_newest_file(
        self, pattern: str = "*", *, case_sensitive: bool | None = None, recurse_symlinks: bool = False
    ) -> SPath | None:
        """Find the most recently modified file matching the given pattern in the directory."""

        return max(
            self.get_folder().glob(pattern, case_sensitive=case_sensitive, recurse_symlinks=recurse_symlinks),
            key=lambda p: p.stat().st_mtime,
            default=None,
        )

    def get_size(self) -> int:
        """Get the size of the file or directory in bytes."""

        if not self.exists():
            from ..exceptions import FileNotExistsError

            raise FileNotExistsError('The given path, "{self}" is not a file or directory!', self.get_size)

        if self.is_file():
            return self.stat().st_size

        return sum(f.stat().st_size for f in self.rglob("*") if f.is_file())

    def is_executable(self) -> bool:
        """Check if the path is executable."""

        return access(self.to_str(), X_OK)


type SPathLike = str | PathLike[str]
