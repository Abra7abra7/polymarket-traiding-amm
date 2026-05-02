"""
Unit tests for CLI argument parsing in __main__.py

Tests parse_args() function.
"""

import pytest
from polymarket_bot.__main__ import parse_args


class TestParseArgs:
    """Test argparse parsing."""

    def test_default_values(self):
        args = parse_args([])
        assert args.config == "config/config.yaml"
        assert args.dry_run is None  # not set → uses config default
        assert args.log_level is None

    def test_dry_run_flag(self):
        args = parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_no_dry_run_flag(self):
        args = parse_args(["--no-dry-run"])
        assert args.dry_run is False

    def test_custom_config(self):
        args = parse_args(["--config", "/custom/path.yaml"])
        assert args.config == "/custom/path.yaml"

    def test_log_level(self):
        for level in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            args = parse_args(["--log-level", level])
            assert args.log_level == level

    def test_invalid_log_level(self):
        with pytest.raises(SystemExit):
            parse_args(["--log-level", "INVALID"])

    def test_combined_flags(self):
        args = parse_args([
            "--config", "/tmp/test.yaml",
            "--dry-run",
            "--log-level", "DEBUG"
        ])
        assert args.config == "/tmp/test.yaml"
        assert args.dry_run is True
        assert args.log_level == "DEBUG"


class TestArgparseHelp:
    """Test that help is registered (not raising)."""

    def test_help_works(self):
        # parse_args(["--help"]) raises SystemExit
        with pytest.raises(SystemExit) as exc:
            parse_args(["--help"])
        assert exc.value.code == 0  # normal exit
