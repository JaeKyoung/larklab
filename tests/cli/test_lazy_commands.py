"""The CLI imports a command's module only when the command is used."""

import subprocess
import sys

import click
import pytest

from larklab.cli import _COMMANDS, cli


@pytest.mark.parametrize("name", sorted(_COMMANDS))
def test_every_listed_command_resolves_to_a_command_of_that_name(name):
    command = cli.get_command(None, name)

    assert isinstance(command, click.Command)
    assert command.name == name


def test_an_unknown_command_is_refused():
    assert cli.get_command(None, "db-nothing") is None


def test_the_command_list_is_sorted_and_complete():
    assert cli.list_commands(None) == sorted(_COMMANDS)
    assert len(_COMMANDS) == 11


def test_db_list_starts_without_loading_ollama_google_or_slack():
    """The point of the lazy group: it is what makes `db-list` start quickly."""
    code = (
        "import sys\n"
        "from larklab.cli import cli\n"
        "cli.get_command(None, 'db-list')\n"
        "heavy = ('ollama', 'googleapiclient', 'slack_sdk')\n"
        "heavy = [m for m in heavy if m in sys.modules]\n"
        "print(heavy)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "[]"
