from pathlib import Path

from tuflow_qaqc.parsing import scan_all_inputs


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
    assert result.control_tree.edges[tcf] == []
    assert any("Read Soils File" in msg for msg in result.debug_log)
