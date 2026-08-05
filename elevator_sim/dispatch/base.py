"""Dispatch policy interface (PLAN §7, Axis 2) — batch-oriented.

Every policy takes the set of currently-unassigned passengers and returns a
mapping `{passenger_id: elevator_id}`. Greedy policies loop internally; the
Hungarian policy solves the batch jointly — same signature either way, so all
policies are interchangeable and the engine calls them identically.

A policy may leave a passenger *out* of the returned mapping (e.g. Hungarian with
more requests than free slots); the engine keeps those unassigned for next tick.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class DispatchPolicy(ABC):
    @abstractmethod
    def dispatch(self, pending, world) -> dict[str, int]:
        ...
