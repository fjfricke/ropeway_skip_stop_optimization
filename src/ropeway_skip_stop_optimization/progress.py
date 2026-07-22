from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import TypeVar

from tqdm.auto import tqdm

T = TypeVar("T")


class ProgressReporter:
    def __init__(self, *, enabled: bool = False, logger: logging.Logger | None = None) -> None:
        self.enabled = enabled
        self.logger = logger or logging.getLogger("ropeway_skip_stop_optimization")

    @contextmanager
    def phase(self, label: str) -> Iterator[None]:
        if not self.enabled:
            yield
            return

        self.logger.info("%s: started", label)
        start = perf_counter()
        try:
            yield
        finally:
            self.logger.info("%s: finished in %.3fs", label, perf_counter() - start)

    def iter(self, iterable: Iterable[T], *, label: str, total: int | None = None) -> Iterator[T]:
        if not self.enabled:
            yield from iterable
            return
        yield from tqdm(iterable, desc=label, total=total, leave=False)

    def report(self, label: str, **values: object) -> None:
        if not self.enabled:
            return
        details = " ".join(
            f"{key}={value}" for key, value in values.items() if value is not None
        )
        self.logger.info("%s%s", label, f" {details}" if details else "")


def configure_progress_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
