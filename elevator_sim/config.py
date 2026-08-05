"""System / building configuration (PLAN §12 defaults model an office building)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SystemConfig:
    """The building + engine parameters (not the workload or scheduler)."""

    n_elevators: int = 16
    n_floors: int = 25
    capacity: int = 10
    dwell: int = 2          # ticks a car pauses per stop (doors open)
    init_floor: int = 1     # all cars start at the lobby, IDLE


@dataclass
class CostWeights:
    """Weights for the cost-function / Hungarian dispatch (PLAN §7, defaults §12).

    These are the tunable *parameters*; the cost *features* (distance, direction,
    load, eta) are computed from live state each call. Set once at construction.
    """

    w_dist: float = 1.0     # floors from car to the pickup (closer = cheaper)
    w_dir: float = 2.0      # penalty if the car isn't already going the rider's way
    w_load: float = 0.5     # how full the car is (balances load across cars)
    w_eta: float = 1.5      # route-aware estimated time-to-pickup (the real ETA)
