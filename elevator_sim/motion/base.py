"""Motion policy interface (PLAN §7, Axis 1)."""

from __future__ import annotations

from abc import ABC, abstractmethod


class MotionPolicy(ABC):
    """Decides, for one elevator, the next floor to head toward.

    The engine handles the actual one-floor step; the policy only chooses the
    target (and may update the car's sweep `direction`). Returns `None` when the
    car has no targets (idle).
    """

    @abstractmethod
    def next_target(self, elevator, world) -> int | None:
        ...
