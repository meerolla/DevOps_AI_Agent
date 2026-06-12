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
