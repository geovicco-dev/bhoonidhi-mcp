"""Keep library stdout off the JSON-RPC wire.

A stdio MCP server speaks JSON-RPC over stdout, so anything else written there
can corrupt the protocol. The ``bhoonidhi-downloader`` SDK prints progress and
warnings to a Rich console (which resolves to ``sys.stdout`` at write time) on
its search paths.

MCP 2.0's stdio transport already diverts the stdout *file descriptor* to
stderr while serving, so in normal client-launched use stray writes cannot reach
the wire. This context manager is the explicit, in-code counterpart: it routes
any SDK console output to stderr on purpose — keeping the client's log readable
and covering contexts where the transport's fd-level diversion does not apply
(tests, alternate transports). Wrap SDK calls that may print with it.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Iterator


@contextlib.contextmanager
def sdk_console_to_stderr() -> Iterator[None]:
    """Send stdout written inside the block to stderr instead.

    Use around ``bhoonidhi-downloader`` calls that emit console output (search
    progress, skipped-selection warnings) so it lands on stderr and never on the
    stdout JSON-RPC channel.
    """
    with contextlib.redirect_stdout(sys.stderr):
        yield
