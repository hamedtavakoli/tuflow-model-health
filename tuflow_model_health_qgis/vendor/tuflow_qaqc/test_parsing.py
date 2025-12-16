from pathlib import Path

from tuflow_model_health_qgis.vendor.tuflow_qaqc.parsing import (
    looks_like_file_path,
    scan_all_inputs,
    group_inputs_by_category,
)
from tuflow_model_health_qgis.vendor.tuflow_qaqc.core import InputCategory


def test_looks_like_file_path_filters_non_files():
    assert looks_like_file_path("data.shp")
    assert looks_like_file_path("..\\soil.tsoilf")
    assert not looks_like_file_path("ON")
    assert not looks_like_file_path("123.45")
    assert not looks_like_file_path("2.5m")
    assert not looks_like_file_path("layer_without_ext")


def test_scan_filters_noise_and_collects_layers(tmp_path: Path):
    control = tmp_path / "model.tcf"
    (tmp_path / "model.tgc").write_text("")

    control.write_text(
        """
Else if Scenario == 2.5m
Set Variable cell_size == 2.5
Soils File == ..\\inputs\\soil.tsoilf
Read GIS == model.gpkg | 2d_bc
BC Database == bc.csv
Geometry Control File == model.tgc
"""
    )

    result = scan_all_inputs(control, wildcards={}, debug=True)

    by_name = {inp.path.name: inp for inp in result.inputs}
    assert "soil.tsoilf" in by_name
    assert by_name["soil.tsoilf"].category == InputCategory.INPUT

    assert "model.gpkg" in by_name
    assert by_name["model.gpkg"].category == InputCategory.GIS
    assert by_name["model.gpkg"].layer == "2d_bc"

    assert "bc.csv" in by_name
    assert by_name["bc.csv"].category == InputCategory.DATABASE

    assert "2.5" not in by_name

    grouped = group_inputs_by_category(result.inputs)
    gis_nodes = grouped[InputCategory.GIS]
    gpkg_node = next(node for node in gis_nodes if node.name == "model.gpkg")
    assert any(child.name == "2d_bc" for child in gpkg_node.children)

    assert any(child.name == "model.tgc" for child in result.control_tree.edges[control])

