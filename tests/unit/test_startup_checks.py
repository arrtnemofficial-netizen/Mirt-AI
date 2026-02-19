from src.server.startup_checks import CheckSeverity, CheckStatus, run_smoke_checks


def test_smoke_checks_return_explicit_statuses() -> None:
    report = run_smoke_checks()

    assert report.status in {"ok", "warning", "failed"}
    assert report.checks

    for item in report.checks:
        assert item.status in {CheckStatus.PASS, CheckStatus.WARN, CheckStatus.FAIL}
        assert item.severity in {CheckSeverity.CRITICAL, CheckSeverity.WARNING}


def test_smoke_checks_compatibility_flow_or_explicit_init_failure() -> None:
    report = run_smoke_checks()
    names = {item.name for item in report.checks}

    if "state_init" in names:
        state_init = next(item for item in report.checks if item.name == "state_init")
        assert state_init.status == CheckStatus.FAIL
        assert state_init.severity == CheckSeverity.CRITICAL
    else:
        assert {
            "state_mutability",
            "state_schema",
            "router_to_schema",
            "checkpointer_init",
        }.issubset(names)
