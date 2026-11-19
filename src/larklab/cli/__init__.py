import importlib
import logging
import sys

import click

# command name -> where it lives. A command's module is imported only when that
# command runs: `db-list` need not wait for the Google, Slack and Ollama libraries.
_COMMANDS = {
    "digest": "larklab.cli.digest:digest",
    "recommend": "larklab.cli.recommend:recommend",
    "db-add": "larklab.cli.library.add:add_paper",
    "db-edit": "larklab.cli.library.edit:edit_paper",
    "db-delete": "larklab.cli.library.edit:delete_paper",
    "db-list": "larklab.cli.library.browse:list_papers",
    "db-search": "larklab.cli.library.browse:search_paper",
    "db-check": "larklab.cli.library.health:check_papers",
    "db-rebuild": "larklab.cli.library.health:rebuild_embeddings",
    "db-export": "larklab.cli.library.backup:export_papers",
    "db-import": "larklab.cli.library.backup:import_papers",
}


class _LazyGroup(click.Group):
    def list_commands(self, ctx):
        return sorted(_COMMANDS)

    def get_command(self, ctx, name):
        location = _COMMANDS.get(name)
        if location is None:
            return None
        module, attribute = location.split(":")
        return getattr(importlib.import_module(module), attribute)


@click.group(cls=_LazyGroup, context_settings={"help_option_names": ["-h", "--help"]})
def cli():
    """LarkLab - Scholar paper digest and management"""
    _show_progress_logs()


def _show_progress_logs() -> None:
    """Library code reports progress through `logging`; show it on stdout.

    The handler is rebuilt on every invocation so it follows the current
    `sys.stdout` (a handler left over from an earlier call would write to a
    stream that may no longer exist).
    """
    package_logger = logging.getLogger("larklab")
    for old_handler in package_logger.handlers[:]:
        package_logger.removeHandler(old_handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    package_logger.addHandler(handler)
    package_logger.setLevel(logging.INFO)
    package_logger.propagate = False
