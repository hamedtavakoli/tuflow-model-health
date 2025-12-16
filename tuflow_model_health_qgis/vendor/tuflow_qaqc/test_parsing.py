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
    assert not looks_like_file_path("layer_without_ext")


def test_scan_filters_noise_and_collects_layers(tmp_path: Path):
    control = tmp_path / "model.tcf"
    control.write_text(
        """
GIS Layer == roads
BC Database == ON
2D BG == 123
GIS Layer == data.gpkg | roads
Soils File == ..\\soil.tsoilf
CSV Database == tables.csv
"""
    )

    result = scan_all_inputs(control, wildcards={}, debug=True)

    names = {inp.path.name for inp in result.inputs}
    assert "data.gpkg" in names
    assert "soil.tsoilf" in names
    assert "tables.csv" in names
    assert "roads" not in names  # layer name without extension

    soils = [i for i in result.inputs if i.path.suffix.lower() == ".tsoilf"]
    assert soils and all(inp.category == InputCategory.INPUT for inp in soils)

    gpkg_inputs = [i for i in result.inputs if i.path.name == "data.gpkg"]
    assert gpkg_inputs and gpkg_inputs[0].category == InputCategory.GIS
    assert gpkg_inputs[0].layer == "roads"

    grouped = group_inputs_by_category(result.inputs)
    gis_nodes = grouped[InputCategory.GIS]
    gpkg_node = next(node for node in gis_nodes if node.name == "data.gpkg")
    assert any(child.name == "roads" for child in gpkg_node.children)

