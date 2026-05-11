"""Planner/Maker/Judge shared dataclasses — PlannerOutput, JudgeVerdict, DefinitionOfDone."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class BranchTask:
    id: str
    branch: str
    priority: int
    weight: float
    query: str
    expected_artifacts: list[str] = field(default_factory=list)


@dataclass
class DefinitionOfDone:
    must_cover_concepts: list[str] = field(default_factory=list)
    must_consider_jurisdictions: list[str] = field(default_factory=list)
    must_address_caveats: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)


@dataclass
class PlannerOutput:
    branches: list[dict[str, object]]      # [{name: str, priority: int, weight: float}]
    jurisdictions: list[str]
    output_type: str
    depth: str
    sub_tasks: list[BranchTask]
    definition_of_done: DefinitionOfDone


@dataclass
class JudgeVerdict:
    verdict: Literal["publish", "revise", "reject"]
    scores: dict[str, float]               # factual_support, completeness,
                                           # jurisdictional_correctness,
                                           # caveat_appropriateness, internal_consistency
    gaps: list[str]
    iteration_brief: str
    iteration: int = 1
    is_fallback: bool = False              # True when forced publish due to api/parse error
