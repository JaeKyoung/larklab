import logging
import sys

import click

from larklab.cli.digest import digest
from larklab.cli.library import LIBRARY_COMMANDS
from larklab.cli.recommend import recommend


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli():
    """LarkLab - Scholar paper digest and management"""
    _show_progress_logs()


for _command in (digest, recommend, *LIBRARY_COMMANDS):
    cli.add_command(_command)


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
