from pathlib import Path

from tuflow_qaqc.core import InputCategory
from tuflow_qaqc.parsing import scan_all_inputs


def test_generic_inputs_are_included(tmp_path: Path) -> None:
    control_dir = tmp_path / "control"
    inputs_dir = tmp_path / "inputs"
    control_dir.mkdir()
    inputs_dir.mkdir()

    rainfall = inputs_dir / "rainfall_100y.csv"
    rainfall.write_text("rain")
    soil = inputs_dir / "soil_params.tsoilf"
    soil.write_text("soil")
    custom_input = inputs_dir / "roughness.custom"
    custom_input.write_text("roughness")

    tcf = control_dir / "model.tcf"
    tcf.write_text(
        "\n".join(
            [
                "Database == ..\\inputs\\rainfall_100y.csv",
                "Soils File == ..\\inputs\\soil_params.tsoilf",
                "Read Roughness == ..\\inputs\\roughness.custom",
            ]
        )
    )

    result = scan_all_inputs(tcf, {})

    categories = {inp.path.name: inp.category for inp in result.inputs}
    assert categories["rainfall_100y.csv"] == InputCategory.DATABASE
    assert categories["soil_params.tsoilf"] == InputCategory.INPUT
    assert categories["roughness.custom"] == InputCategory.INPUT

    assert result.model_tree is not None
    collected = set()

    def _collect(node):
        collected.add(node.name)
        for child in node.children:
            _collect(child)

    _collect(result.model_tree)
    assert {"rainfall_100y.csv", "soil_params.tsoilf", "roughness.custom"}.issubset(
        collected
    )
