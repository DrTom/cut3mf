"""Tests build a model like the intended workflow: a body with text sunk 1 mm
into its top, plus a 1 mm plate above the surface that joins the letters."""
import zipfile
from pathlib import Path

import pytest
import trimesh

from cut3mf import CutError, cut_file
from cut3mf.cli import _fix_negative_axis, main


def _box(extents, center):
    b = trimesh.creation.box(extents)
    b.apply_translation(center)
    return b


def _model(path: Path, units: str = "millimeters", scale: float = 1.0) -> Path:
    body = _box((40, 20, 10), (0, 0, 5))                       # z 0..10
    l1 = _box((4, 8, 2), (-8, 0, 10))                         # z 9..11
    l2 = _box((4, 8, 2), (8, 0, 10))
    plate = _box((24, 12, 1), (0, 0, 10.5))                   # z 10..11
    text = trimesh.boolean.union([l1, l2, plate], engine="manifold")
    s = trimesh.Scene()
    s.add_geometry(body, node_name="body", geom_name="body")
    s.add_geometry(text, node_name="text", geom_name="text")
    if scale != 1.0:
        s = s.scaled(scale)
    s.export(path)
    if units != "millimeters":
        # trimesh always writes unit="millimeter"; patch it like a CAD tool exporting in meters.
        with zipfile.ZipFile(path) as z:
            files = {n: z.read(n) for n in z.namelist()}
        files["3D/3dmodel.model"] = files["3D/3dmodel.model"].replace(
            b'unit="millimeter"', f'unit="{units}"'.encode(), 1)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for n, data in files.items():
                z.writestr(n, data)
    return path


def _load(path):
    s = trimesh.load(path, force="scene")
    if s.units not in (None, "millimeters"):
        s = s.convert_units("millimeters")
    return s


def test_top_plate_removed(tmp_path):
    r = cut_file(_model(tmp_path / "m.3mf"))
    assert r.output == tmp_path / "m_cut.3mf"
    s = _load(r.output)
    text, body = s.geometry["text"], s.geometry["body"]
    parts = text.split()
    assert len(parts) == 2                                   # letters now separate
    assert all(p.is_watertight for p in parts)
    assert text.volume == pytest.approx(2 * 4 * 8 * 1, rel=1e-2)
    assert text.bounds[1][2] == pytest.approx(10.0, abs=0.01)
    assert body.volume == pytest.approx(40 * 20 * 10, rel=1e-3)


def test_meter_units(tmp_path):
    src = _model(tmp_path / "m.3mf", units="meter", scale=0.001)
    r = cut_file(src)
    assert r.extreme == pytest.approx(11.0, abs=0.01)        # read as mm
    s = _load(r.output)
    assert len(s.geometry["text"].split()) == 2


def test_bottom_axis(tmp_path):
    r = cut_file(_model(tmp_path / "m.3mf"), axis="bottom", depth=2)
    assert r.axis == "-z"
    s = _load(r.output)
    assert s.geometry["body"].bounds[0][2] == pytest.approx(2.0, abs=0.01)


def test_everything_removed_raises(tmp_path):
    with pytest.raises(CutError):
        cut_file(_model(tmp_path / "m.3mf"), depth=100)


def test_bad_axis_raises(tmp_path):
    with pytest.raises(CutError):
        cut_file(_model(tmp_path / "m.3mf"), axis="w")


def test_negative_axis_argv():
    assert _fix_negative_axis(["f.3mf", "--axis", "-z"]) == ["f.3mf", "--axis=-z"]
    assert _fix_negative_axis(["f.3mf", "--axis", "top"]) == ["f.3mf", "--axis", "top"]


def test_cli(tmp_path, capsys):
    src = _model(tmp_path / "m.3mf")
    assert main([str(src), "--axis", "-z", "-o", str(tmp_path / "o.3mf")]) == 0
    assert (tmp_path / "o.3mf").exists()
    assert main([str(src), "-d", "100"]) == 1
    assert "nothing left" in capsys.readouterr().err


def _model_xml(path):
    from lxml import etree
    root = etree.fromstring(zipfile.ZipFile(path).read("3D/3dmodel.model"))
    ns = {"m": root.nsmap[None]}
    return root, ns


def test_3mf_is_one_object_with_parts(tmp_path):
    r = cut_file(_model(tmp_path / "m.3mf"))
    root, ns = _model_xml(r.output)
    items = root.findall("m:build/m:item", ns)
    assert len(items) == 1                                   # one object on the plate
    parent = root.find(f"m:resources/m:object[@id='{items[0].get('objectid')}']", ns)
    assert parent.get("name") == "m"
    assert len(parent.findall("m:components/m:component", ns)) == 2
    assert set(_load(r.output).geometry) == {"body", "text"}


def test_3mf_separate_objects(tmp_path):
    r = cut_file(_model(tmp_path / "m.3mf"), separate=True)
    root, ns = _model_xml(r.output)
    assert len(root.findall("m:build/m:item", ns)) == 2
    assert root.find("m:resources/m:object/m:components", ns) is None
