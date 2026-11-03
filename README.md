# cut3mf

Cut a slab off one face of a 3MF or STL model before slicing.

Made for a common CAD-to-slicer workaround: when text is embedded in a
surface, the many separate letter bodies often cause trouble, in the CAD tool,
on export, or in the slicer. Model a thin "helper plate" (e.g. 1 mm) on top of
the surface that holds the letters together, export, then let `cut3mf` remove
that plate. You get clean, watertight letter bodies flush with the surface,
as separate parts of one object, so you can assign them their own filament.

It works with any CAD tool that exports 3MF, STL or OBJ (Onshape, Fusion,
FreeCAD, SolidWorks, ...) and any slicer that imports them (Bambu Studio,
OrcaSlicer, PrusaSlicer, Cura, ...).

## Install

```bash
pipx install cut3mf      # or: pip install cut3mf
```

## Usage

```bash
cut3mf part.3mf                    # remove the top 1 mm -> part_cut.3mf
cut3mf part.3mf -d 1.2 -o out.3mf  # remove the top 1.2 mm
cut3mf part.3mf --axis bottom      # plate on the bottom (same as --axis -z)
cut3mf part.3mf --at 14.5          # keep everything below Z = 14.5 mm
```

| Option | Meaning |
|---|---|
| `-d, --depth` | Thickness to remove from the outermost face, mm (default 1.0) |
| `-a, --axis` | Face with the plate: `top`, `bottom`, `front`, `back`, `left`, `right`, or `x`, `-x`, `y`, `-y`, `z`, `-z` (default `top`) |
| `--at` | Cut at an absolute coordinate (mm) instead of a depth |
| `-o, --output` | Output file (default `<input>_cut.<ext>`) |
| `--separate` | 3MF: write each body as its own object instead of one object with parts |
| `--eps` | Extra cut depth against coplanar slivers, mm (default 0.001) |

### How it works

- All objects are measured together, so every object is cut at the same plane.
- 3MF units are respected and converted to millimeters (some tools, e.g. Onshape, export in meters). STL has no units and is taken as millimeters.
- 3MF output is one object whose bodies are its parts (3MF components), so
  slicers such as Bambu Studio, OrcaSlicer and PrusaSlicer load it as a single
  object with several parts, each of which can get its own filament. Use
  `--separate` to get independent objects instead. STL stores only one
  combined mesh.
- The cut uses the [Manifold](https://github.com/elalish/manifold) kernel, so cut faces are closed and results stay watertight.
- The cut goes 1 µm deeper than requested, because the plate's underside usually lies exactly on the cut plane and an exact cut leaves zero-thickness slivers.

Limits: the cut is a flat plane, and the plate must be the outermost part of the
model in the chosen direction. 3MF output keeps the objects and their names, but
not slicer project data such as filament assignments or print settings, so
cut the exported model before you set it up in the slicer.

### Python API

```python
from cut3mf import cut_file

result = cut_file("part.3mf", axis="bottom", depth=1.0)
print(result.output, result.kept)
```

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
pytest
```

## Releasing

Releases are published to PyPI by GitHub Actions using trusted publishing.
Bump `version` in `pyproject.toml`, commit, then run:

```bash
scripts/git_tag_and_push
```

The script runs the tests, tags the commit as `v<version>` and pushes the tag;
the publish workflow builds and uploads that version.

## License

MIT
