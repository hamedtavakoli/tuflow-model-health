from tuflow_model_health_qgis.vendor.tuflow_qaqc.wildcards import validate_wildcards


def test_run_test_blocks_on_missing_wildcards():
    result = validate_wildcards(
        "model~e1~.tcf",
        {},
        run_test=True,
        stages_enabled={"stage0_1": True, "run_test": True},
        will_build_paths=True,
    )

    assert result.severity == "error"
    assert result.ok_to_proceed is False
    assert result.missing == {"e1"}


def test_no_run_test_allows_warning_when_paths_not_needed():
    result = validate_wildcards(
        "model~s1~.tcf",
        {},
        run_test=False,
        stages_enabled={"stage0_1": False, "run_test": False},
        will_build_paths=False,
    )

    assert result.severity == "warning"
    assert result.ok_to_proceed is True
    assert "Proceeding" in result.message


def test_missing_blocks_when_paths_required_without_run_test():
    result = validate_wildcards(
        "model~s1~.tcf",
        {},
        run_test=False,
        stages_enabled={"stage0_1": True, "run_test": False},
        will_build_paths=True,
    )

    assert result.severity == "error"
    assert result.ok_to_proceed is False
    assert result.missing == {"s1"}


def test_partial_wildcards_detect_missing_set():
    result = validate_wildcards(
        "run~e1~_~s1~.tcf",
        {"e1": "001"},
        run_test=True,
        stages_enabled={"stage0_1": True, "run_test": True},
        will_build_paths=True,
    )

    assert result.missing == {"s1"}
