from orchestrator.main import build_parser


def test_run_parser_accepts_part3_contract_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "run",
            "--repo",
            "./my-app",
            "--cluster",
            "k3d-mycluster",
            "--registry",
            "ghcr.io/org/my-app",
            "--namespace",
            "my-app",
        ]
    )

    assert args.command == "run"
    assert args.repo == "./my-app"
    assert args.cluster == "k3d-mycluster"
    assert args.registry == "ghcr.io/org/my-app"
    assert args.namespace == "my-app"
    assert args.no_draft_pr is False


def test_run_parser_supports_no_draft_pr_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "run",
            "--repo",
            "./my-app",
            "--cluster",
            "k3d-mycluster",
            "--registry",
            "ghcr.io/org/my-app",
            "--namespace",
            "my-app",
            "--no-draft-pr",
        ]
    )
    assert args.command == "run"
    assert args.no_draft_pr is True


def test_retry_parser_accepts_from_step() -> None:
    parser = build_parser()
    args = parser.parse_args(["retry", "--repo", "./my-app", "--from-step", "test"])
    assert args.command == "retry"
    assert args.from_step == "test"
    assert args.auto_approve is False


def test_retry_parser_rejects_invalid_step() -> None:
    import pytest
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["retry", "--repo", "./my-app", "--from-step", "plan"])
