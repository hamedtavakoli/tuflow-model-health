from pathlib import Path

from pathlib import Path

from tuflow_model_health_qgis.vendor.tuflow_qaqc.core import InputCategory
from tuflow_model_health_qgis.vendor.tuflow_qaqc.parsing import scan_all_inputs


def test_read_soils_file_is_detected(tmp_path: Path) -> None:
    control_dir = tmp_path / "control"
    model_dir = tmp_path / "model"
    control_dir.mkdir()
    model_dir.mkdir()

    soil_file = model_dir / "soil_params.tsoilf"
    soil_file.write_text("dummy soils contents")
    alt_soil_file = model_dir / "alt_soil_params.tsoilf"
    alt_soil_file.write_text("alt")

    tcf = control_dir / "model.tcf"
    tcf.write_text(
        "\n".join(
            [
                'Read Soils File == ..\\model\\soil_params.tsoilf ! inline comment',
                'Read Soils File = "../model/alt_soil_params.tsoilf" ; semicolon comment',
            ]
        )
    )

    result = scan_all_inputs(tcf, {}, debug=True)

    soil_paths = {inp.path for inp in result.inputs}
    assert soil_file.resolve() in soil_paths
    assert alt_soil_file.resolve() in soil_paths
    for soil_ref in [
        inp
        for inp in result.inputs
        if inp.path in {soil_file.resolve(), alt_soil_file.resolve()}
    ]:
        assert soil_ref.category == InputCategory.INPUT

    assert result.model_tree is not None
    names = []

    def _collect_names(node):
        names.append(node.name)
        for child in node.children:
            _collect_names(child)

    _collect_names(result.model_tree)
    assert soil_file.name in names
    assert alt_soil_file.name in names
    assert result.control_tree.edges[tcf] == []
    assert any("Read Soils File" in msg for msg in result.debug_log)
