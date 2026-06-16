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


def test_activate_parser_accepts_required_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "activate",
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
    assert args.command == "activate"
    assert args.repo == "./my-app"
    assert args.cluster == "k3d-mycluster"
    assert args.registry == "ghcr.io/org/my-app"
    assert args.namespace == "my-app"
    assert args.auto_approve_deploy is False


def test_activate_parser_supports_auto_approve_deploy() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "activate",
            "--repo",
            "./my-app",
            "--cluster",
            "k3d-mycluster",
            "--registry",
            "ghcr.io/org/my-app",
            "--namespace",
            "my-app",
            "--auto-approve-deploy",
        ]
    )
    assert args.command == "activate"
    assert args.auto_approve_deploy is True
