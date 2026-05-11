"""Adversarial test suite for lex-agents robustness evaluation."""

from .types import AdversarialCase, AttackLevel, RobustnessMetrics
from .perturbations import (
    char_typo,
    char_homoglyph,
    char_insertion,
    word_synonym,
    word_noise,
    sentence_irrelevant,
    sentence_contradictory,
    sentence_reorder,
    semantic_formal,
    semantic_perspective,
    semantic_passive,
)
from .evaluator import AdversarialEvaluator, has_required_caveat, jailbreak_accepted

__all__ = [
    "AdversarialCase",
    "AttackLevel",
    "RobustnessMetrics",
    "char_typo",
    "char_homoglyph",
    "char_insertion",
    "word_synonym",
    "word_noise",
    "sentence_irrelevant",
    "sentence_contradictory",
    "sentence_reorder",
    "semantic_formal",
    "semantic_perspective",
    "semantic_passive",
    "AdversarialEvaluator",
    "has_required_caveat",
    "jailbreak_accepted",
]
