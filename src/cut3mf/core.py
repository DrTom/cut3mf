"""Core cutting logic: remove a slab from one face of a multi-object mesh."""
from __future__ import annotations

import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import manifold3d as mf
import numpy as np
import trimesh
from lxml import etree

log = logging.getLogger(__name__)

AXES = {"x": 0, "y": 1, "z": 2}
ALIASES = {
    "top": "z", "bottom": "-z",
    "back": "y", "front": "-y",
    "right": "x", "left": "-x",
}
_MM = ("mm", "millimeter", "millimeters")
_NS_3MF = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_NS_MAT = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"
# Bambu Studio and OrcaSlicer read part names only from this file; without it
# every part is named after its parent object ("name", "name_2", ...).
_BAMBU_MODEL_CONFIG = "Metadata/model_settings.config"


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


def _norm_color(c: str) -> str | None:
    c = c.strip().upper()
    if len(c) == 7 and c.startswith("#"):
        c += "FF"
    return c if len(c) == 9 and c.startswith("#") else None


def read_3mf_colors(path: Path) -> dict[str, str]:
    """Return {object name: "#RRGGBBAA"} for the colored objects of a 3MF,
    ordered like the colors in the file's palettes.

    trimesh drops 3MF colors on load, so they are read here directly. Supports
    color groups and base materials, set on the object or on its triangles
    (then the most common color wins). Objects without a color of their own
    inherit the color of the object that contains them as a component.
    """
    ns = {"c": _NS_3MF, "m": _NS_MAT}
    with zipfile.ZipFile(path) as z:
        roots = [etree.fromstring(z.read(n)) for n in z.namelist()
                 if n.lower().endswith(".model")]

    palettes: dict[str, list[str | None]] = {}
    objects: dict[str, etree._Element] = {}
    for root in roots:
        for g in root.iterfind("c:resources/m:colorgroup", ns):
            palettes[g.get("id")] = [_norm_color(c.get("color", "")) for c in g.iterfind("m:color", ns)]
        for g in root.iterfind("c:resources/c:basematerials", ns):
            palettes[g.get("id")] = [_norm_color(b.get("displaycolor", "")) for b in g.iterfind("c:base", ns)]
        for o in root.iterfind("c:resources/c:object", ns):
            objects[o.get("id")] = o

    def lookup(pid, index):
        colors = palettes.get(pid) or []
        i = int(index or 0)
        return colors[i] if 0 <= i < len(colors) else None

    own: dict[str, str | None] = {}
    for oid, o in objects.items():
        color = lookup(o.get("pid"), o.get("pindex"))
        if color is None:
            counts: dict[str, int] = {}
            for t in o.iterfind("c:mesh/c:triangles/c:triangle", ns):
                tc = lookup(t.get("pid", o.get("pid")), t.get("p1"))
                if tc:
                    counts[tc] = counts.get(tc, 0) + 1
            color = max(counts, key=counts.get) if counts else None
        own[oid] = color

    resolved: dict[str, str | None] = {}

    def walk(oid, inherited):
        color = own.get(oid) or inherited
        o = objects.get(oid)
        if o is None:
            return
        if o.find("c:mesh", ns) is not None:
            resolved.setdefault(oid, color)
        for c in o.iterfind("c:components/c:component", ns):
            walk(c.get("objectid"), color)

    for root in roots:
        for item in root.iterfind("c:build/c:item", ns):
            walk(item.get("objectid"), None)

    by_name: dict[str, str | None] = {}
    for oid, color in resolved.items():
        name = objects[oid].get("name", "")
        if name in by_name and by_name[name] != color:
            by_name[name] = None  # same name, different colors: ambiguous
        else:
            by_name[name] = color
    order = list(dict.fromkeys(c for cs in palettes.values() for c in cs if c))
    named = [(n, c) for n, c in by_name.items() if c]
    return dict(sorted(named, key=lambda nc: order.index(nc[1])))


def load_scene(path: Path) -> trimesh.Scene:
    """Load a mesh file as a scene in millimeters.

    For 3MF, the object colors are kept in ``scene.metadata["colors"]``.
    """
    path = Path(path)
    scene = trimesh.load(path, force="scene")
    if scene.units and scene.units not in _MM:
        # Some CAD tools (e.g. Onshape) write 3MF in meters.
        log.info("converting units: %s -> millimeters", scene.units)
        scene = scene.convert_units("millimeters")
    elif not scene.units:
        log.info("file has no units, assuming millimeters")
    if path.suffix.lower() == ".3mf":
        scene.metadata["colors"] = read_3mf_colors(path)
    return scene


def cut_scene(
    scene: trimesh.Scene,
    *,
    axis: str = "z",
    depth: float = 1.0,
    at: float | None = None,
    eps: float = 0.001,
    group: str | None = None,
) -> tuple[trimesh.Scene, dict]:
    """Cut a slab off one face of a scene. Returns (new scene, info dict).

    With ``group``, all kept bodies become parts of one parent node of that
    name. In 3MF this is one object with components, which slicers load as a
    single object with several parts instead of separate objects.
    """
    ai, sign, axis_name = parse_axis(axis)

    # Bake transforms so all objects share one coordinate system.
    geoms: dict[str, trimesh.Trimesh] = {}
    in_colors = scene.metadata.get("colors", {})
    colors: dict[str, str] = {}
    for node in scene.graph.nodes_geometry:
        tf, gname = scene.graph[node]
        g = scene.geometry[gname].copy()
        g.apply_transform(tf)
        geoms[node] = g
        color = in_colors.get(gname) or in_colors.get(node)
        if color:
            colors[node] = color
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

    results: dict[str, trimesh.Trimesh] = {}
    dropped = []
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
        results[name] = res

    if not results:
        raise CutError(
            f"nothing left after cutting at {axis_name}={cut:.3f} mm; "
            "check --depth, --axis and the model's units"
        )

    out = trimesh.Scene()
    out.units = "millimeters"
    # Keep the input's color order; slicers number filaments by it.
    order = list(dict.fromkeys(in_colors.values()))
    kept_colors = [(n, colors[n]) for n in results if n in colors]
    out.metadata["colors"] = dict(sorted(kept_colors, key=lambda nc: order.index(nc[1])))
    parent = None
    if group is not None:
        parent = group
        while parent in results:
            parent += "_group"
        out.graph.update(frame_from=out.graph.base_frame, frame_to=parent)
    for name, res in results.items():
        out.add_geometry(res, node_name=name, geom_name=name, parent_node_name=parent)
    return out, {"axis": axis_name, "cut": cut, "extreme": extreme,
                 "kept": list(results), "dropped": dropped}


def _finish_3mf(path: Path, colors: dict[str, str]) -> None:
    """Add what trimesh's 3MF writer leaves out: object colors, and a
    Bambu/Orca model config so the parts of a grouped object keep their names.
    """
    with zipfile.ZipFile(path) as z:
        files = {i.filename: (i, z.read(i)) for i in z.infolist()}
    root = etree.fromstring(files["3D/3dmodel.model"][1])
    ns = {"c": _NS_3MF}
    resources = root.find("c:resources", ns)
    objects = {o.get("id"): o for o in resources.iterfind("c:object", ns)}

    # Colors as one standard color group, referenced by each colored mesh object.
    palette = list(dict.fromkeys(colors.values()))  # keeps the input's order
    if palette:
        gid = str(max(int(i) for i in objects) + 1)
        group = etree.Element(f"{{{_NS_MAT}}}colorgroup", id=gid)
        for c in palette:
            etree.SubElement(group, f"{{{_NS_MAT}}}color", color=c)
        resources.insert(0, group)  # resources must come before their users
        for o in objects.values():
            color = colors.get(o.get("name", ""))
            if color and o.find("c:mesh", ns) is not None:
                o.set("pid", gid)
                o.set("pindex", str(palette.index(color)))
        files["3D/3dmodel.model"] = (
            files["3D/3dmodel.model"][0],
            etree.tostring(root, xml_declaration=True, encoding="UTF-8"),
        )

    # Bambu Studio and OrcaSlicer read part names only from their own config.
    # They ignore part colors when assigning filaments, so the config also
    # gives each color its own filament number, in palette order.
    config = etree.Element("config")
    for item in root.iterfind("c:build/c:item", ns):
        parent = objects[item.get("objectid")]
        comps = parent.findall("c:components/c:component", ns)
        if not comps:
            continue
        obj = etree.SubElement(config, "object", id=parent.get("id"))
        etree.SubElement(obj, "metadata", key="name", value=parent.get("name", ""))
        for c in comps:
            part = etree.SubElement(obj, "part", id=c.get("objectid"), subtype="normal_part")
            name = objects[c.get("objectid")].get("name", "")
            etree.SubElement(part, "metadata", key="name", value=name)
            if name in colors:
                extruder = str(palette.index(colors[name]) + 1)
                etree.SubElement(part, "metadata", key="extruder", value=extruder)
    if len(config):
        data = etree.tostring(config, xml_declaration=True, encoding="UTF-8", pretty_print=True)
        # Fixed date, like the other entries, so the file carries no timestamp.
        info = zipfile.ZipInfo(_BAMBU_MODEL_CONFIG, date_time=(1980, 1, 1, 0, 0, 0))
        files[_BAMBU_MODEL_CONFIG] = (info, data)

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for info, content in files.values():
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, content)


def default_output(path: Path) -> Path:
    return path.with_name(path.stem + "_cut" + path.suffix)


def cut_file(
    input: str | Path,
    output: str | Path | None = None,
    *,
    separate: bool = False,
    **kwargs,
) -> CutResult:
    """Cut a mesh file and write the result. kwargs go to :func:`cut_scene`.

    3MF output is written as one object with the bodies as its parts, unless
    ``separate`` is set, which writes each body as its own object.
    """
    src = Path(input)
    dst = Path(output) if output else default_output(src)
    if not separate and dst.suffix.lower() == ".3mf":
        kwargs.setdefault("group", src.stem)
    scene, info = cut_scene(load_scene(src), **kwargs)
    scene.export(dst)
    if dst.suffix.lower() == ".3mf":
        _finish_3mf(dst, scene.metadata.get("colors", {}))
    return CutResult(output=dst, **info)
