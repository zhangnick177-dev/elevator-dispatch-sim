"""Results-writer interface (PLAN §9).

`metrics.py` computes, `io/writers.py` saves. Keeping saving behind this
interface lets Phase 2 swap `CsvWriter` -> `SupabaseWriter` with the
metrics/engine core untouched — the orchestrator just picks a writer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class ResultsWriter(ABC):
    @abstractmethod
    def write(self, result, metrics, outdir: str | Path) -> None:
        """Persist a finished run: `result` (RunResult, for the positions log)
        and `metrics` (Metrics, for passengers + summary) to `outdir`."""
        ...
