# cut3mf

Cut a slab off one face of a 3MF or STL model before slicing.

Made for a common Onshape → Bambu Studio workaround: when text is embedded in a
surface, the separate letters often cause trouble on export or in the slicer.
Model a thin "helper plate" (e.g. 1 mm) on top of the surface that holds the
letters together, export, then let `cut3mf` remove that plate. You get clean,
watertight letter bodies flush with the surface, still as separate objects, so
you can assign them their own filament.

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
| `--eps` | Extra cut depth against coplanar slivers, mm (default 0.001) |

### How it works

- All objects are measured together, so every object is cut at the same plane.
- Units are converted to millimeters (Onshape writes 3MF in meters).
- The cut uses the [Manifold](https://github.com/elalish/manifold) kernel, so cut faces are closed and results stay watertight.
- The cut goes 1 µm deeper than requested, because the plate's underside usually lies exactly on the cut plane and an exact cut leaves zero-thickness slivers.

Limits: the cut is a flat plane, and the plate must be the outermost part of the
model in the chosen direction. 3MF output keeps the objects and their names, but
not slicer-specific project data such as filament assignments.

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

Releases are published to PyPI from GitHub Actions using trusted publishing.
Tag a version and publish a GitHub release:

```bash
git tag v0.1.0 && git push origin v0.1.0
gh release create v0.1.0 --generate-notes
```

The version number comes from the git tag.

## License

MIT
