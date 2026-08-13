"""Worker entrypoint. `uv run emulsion-worker`, or the container's command."""

from __future__ import annotations

import logging

from .runner import run_forever
from .runtime import bootstrap, settings


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
    )
    bootstrap()
    logging.getLogger("emulsion.worker").info(
        "starting worker — adapter=%s data=%s", settings().adapter, settings().data_dir
    )
    run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
