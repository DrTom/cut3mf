"""cut3mf: cut a slab off one face of a 3MF/STL model before slicing."""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("cut3mf")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0.0.0"

from .core import CutError, CutResult, cut_file, cut_scene, load_scene  # noqa: E402

__all__ = ["CutError", "CutResult", "cut_file", "cut_scene", "load_scene", "__version__"]
