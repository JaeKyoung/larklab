import contextlib
import io
import logging

import pytest

from larklab.cli import _show_progress_logs


@pytest.fixture(autouse=True)
def restore_package_logger():
    package_logger = logging.getLogger("larklab")
    saved = (package_logger.handlers[:], package_logger.level, package_logger.propagate)
    yield
    package_logger.handlers[:], package_logger.level, package_logger.propagate = saved


def test_progress_lines_follow_whatever_stdout_is_current():
    """Two invocations in one process (a bot, or tests) must both be heard."""
    for _ in range(2):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            _show_progress_logs()
            logging.getLogger("larklab.pipelines.example").info("progress line")

        assert buffer.getvalue() == "progress line\n"


def test_debug_chatter_stays_out_of_the_cron_log():
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _show_progress_logs()
        logging.getLogger("larklab.example").debug("noise")

    assert buffer.getvalue() == ""
