"""Adversarial test suite for lex-agents robustness evaluation."""

from .evaluator import AdversarialEvaluator, has_required_caveat, jailbreak_accepted
from .perturbations import (
    char_homoglyph,
    char_insertion,
    char_typo,
    semantic_formal,
    semantic_passive,
    semantic_perspective,
    sentence_contradictory,
    sentence_irrelevant,
    sentence_reorder,
    word_noise,
    word_synonym,
)
from .types import AdversarialCase, AttackLevel, RobustnessMetrics

__all__ = [
    "AdversarialCase",
    "AdversarialEvaluator",
    "AttackLevel",
    "RobustnessMetrics",
    "char_homoglyph",
    "char_insertion",
    "char_typo",
    "has_required_caveat",
    "jailbreak_accepted",
    "semantic_formal",
    "semantic_passive",
    "semantic_perspective",
    "sentence_contradictory",
    "sentence_irrelevant",
    "sentence_reorder",
    "word_noise",
    "word_synonym",
]
