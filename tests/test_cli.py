import pytest

from psx_decomp_studio import __version__
from psx_decomp_studio.cli import main


def test_main_runs(capsys):
    assert main([]) == 0
    assert "work in progress" in capsys.readouterr().out


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out
