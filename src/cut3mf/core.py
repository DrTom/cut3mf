"""Core cutting logic: remove a slab from one face of a multi-object mesh."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import manifold3d as mf
import numpy as np
import trimesh

log = logging.getLogger(__name__)

AXES = {"x": 0, "y": 1, "z": 2}
ALIASES = {
    "top": "z", "bottom": "-z",
    "back": "y", "front": "-y",
    "right": "x", "left": "-x",
}
_MM = ("mm", "millimeter", "millimeters")


class CutError(Exception):
    """Raised when the input cannot be cut."""


@dataclass
class CutResult:
    axis: str
    cut: float
    extreme: float
    output: Path
    kept: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)


def parse_axis(axis: str) -> tuple[int, float, str]:
    """Return (axis index, sign, normalized name) for 'z', '-y', 'bottom', ..."""
    a = ALIASES.get(axis.lower(), axis.lower())
    name = a.lstrip("+-")
    if name not in AXES:
        raise CutError(
            f"unknown axis '{axis}' (use top/bottom/front/back/left/right, "
            "or x/y/z with an optional minus sign)"
        )
    sign = -1.0 if a.startswith("-") else 1.0
    return AXES[name], sign, ("-" if sign < 0 else "") + name


def _to_manifold(mesh: trimesh.Trimesh) -> mf.Manifold:
    m = mf.Mesh(
        vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
        tri_verts=np.asarray(mesh.faces, dtype=np.uint32),
    )
    return mf.Manifold(m)


def _from_manifold(man: mf.Manifold) -> trimesh.Trimesh:
    m = man.to_mesh()
    return trimesh.Trimesh(
        vertices=np.asarray(m.vert_properties)[:, :3],
        faces=np.asarray(m.tri_verts),
        process=True,
    )


def load_scene(path: Path) -> trimesh.Scene:
    """Load a mesh file as a scene in millimeters."""
    scene = trimesh.load(path, force="scene")
    if scene.units and scene.units not in _MM:
        # Onshape writes 3MF in meters, for example.
        log.info("converting units: %s -> millimeters", scene.units)
        scene = scene.convert_units("millimeters")
    elif not scene.units:
        log.info("file has no units, assuming millimeters")
    return scene


def cut_scene(
    scene: trimesh.Scene,
    *,
    axis: str = "z",
    depth: float = 1.0,
    at: float | None = None,
    eps: float = 0.001,
) -> tuple[trimesh.Scene, dict]:
    """Cut a slab off one face of a scene. Returns (new scene, info dict)."""
    ai, sign, axis_name = parse_axis(axis)

    # Bake transforms so all objects share one coordinate system.
    geoms: dict[str, trimesh.Trimesh] = {}
    for node in scene.graph.nodes_geometry:
        tf, gname = scene.graph[node]
        g = scene.geometry[gname].copy()
        g.apply_transform(tf)
        geoms[node] = g
    if not geoms:
        raise CutError("no geometry found")

    all_v = np.vstack([g.vertices for g in geoms.values()])
    extreme = float(all_v[:, ai].max() if sign > 0 else all_v[:, ai].min())
    cut = at if at is not None else extreme - sign * depth
    # The plate's underside usually lies exactly on the cut plane; cutting
    # exactly there leaves zero-thickness slivers, so cut a hair deeper.
    cut -= sign * eps

    # Keep the side away from the plate. Manifold keeps normal . x >= offset.
    normal = [0.0, 0.0, 0.0]
    normal[ai] = -sign
    offset = -sign * cut

    out = trimesh.Scene()
    out.units = "millimeters"
    kept, dropped = [], []
    for name, g in geoms.items():
        if not g.is_watertight:
            log.warning("'%s' is not watertight, trying anyway", name)
        man = _to_manifold(g)
        if man.status() != mf.Error.NoError:
            raise CutError(
                f"'{name}' is not a valid solid ({man.status()}); "
                "re-export or repair the mesh first"
            )
        trimmed = man.trim_by_plane(normal, offset)
        res = None if trimmed.is_empty() else _from_manifold(trimmed)
        if res is not None:
            parts = [c for c in res.split(only_watertight=False) if abs(c.volume) > 1e-6]
            res = (trimesh.util.concatenate(parts) if len(parts) > 1 else parts[0]) if parts else None
        if res is None:
            log.info("'%s' lies completely in the removed slab, dropped", name)
            dropped.append(name)
            continue
        out.add_geometry(res, node_name=name, geom_name=name)
        kept.append(name)

    if not kept:
        raise CutError(
            f"nothing left after cutting at {axis_name}={cut:.3f} mm; "
            "check --depth, --axis and the model's units"
        )
    return out, {"axis": axis_name, "cut": cut, "extreme": extreme,
                 "kept": kept, "dropped": dropped}


def default_output(path: Path) -> Path:
    return path.with_name(path.stem + "_cut" + path.suffix)


def cut_file(
    input: str | Path,
    output: str | Path | None = None,
    **kwargs,
) -> CutResult:
    """Cut a mesh file and write the result. kwargs go to :func:`cut_scene`."""
    src = Path(input)
    dst = Path(output) if output else default_output(src)
    scene, info = cut_scene(load_scene(src), **kwargs)
    scene.export(dst)
    return CutResult(output=dst, **info)
