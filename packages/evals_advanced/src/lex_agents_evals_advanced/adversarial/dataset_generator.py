"""Generate adversarial dataset from golden_dataset YAML cases."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import yaml

from .perturbations import (
    char_typo,
    indirect_injection,
    jailbreak,
    semantic_passive,
    sentence_irrelevant,
    word_synonym,
)
from .types import AdversarialCase, AttackLevel

# One representative perturbation per attack level
_LEVEL_CONFIG: dict[int, tuple[str, str, Callable[[str], str]]] = {
    AttackLevel.CHAR: ("char_typo", "level_1_char", lambda q: char_typo(q)),
    AttackLevel.WORD: ("word_synonym", "level_2_word", lambda q: word_synonym(q)),
    AttackLevel.SENTENCE: (
        "sentence_irrelevant",
        "level_3_sentence",
        lambda q: sentence_irrelevant(q),
    ),
    AttackLevel.SEMANTIC: (
        "semantic_passive",
        "level_4_semantic",
        lambda q: semantic_passive(q),
    ),
    AttackLevel.JAILBREAK: (
        "jailbreak",
        "level_5_jailbreak",
        # template_index is set per-case below
        lambda q: jailbreak(q, 0),
    ),
    AttackLevel.INDIRECT_INJECTION: (
        "indirect_injection",
        "level_6_indirect_injection",
        lambda q: indirect_injection(q, 0),
    ),
}


def _load_golden_cases(golden_dir: Path, n: int) -> list[dict]:
    """Load first n YAML files (alphabetically) from golden_dir."""
    files = sorted(golden_dir.glob("*.yaml"))[:n]
    cases = []
    for f in files:
        with f.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
            if data:
                cases.append(data)
    return cases


def generate_dataset(
    golden_dir: Path,
    output_dir: Path,
    n_base_cases: int = 30,
) -> list[AdversarialCase]:
    """Generate adversarial cases from golden dataset.

    For each of the first n_base_cases golden cases and each attack level (1-6),
    one adversarial variant is generated using the representative perturbation.

    Saves each case as YAML in output_dir/level_<N>_<name>/.
    Returns the list of AdversarialCase objects.
    """
    golden_cases = _load_golden_cases(golden_dir, n_base_cases)
    adversarial_cases: list[AdversarialCase] = []

    for level in AttackLevel:
        attack_type, dir_name, _perturb_fn = _LEVEL_CONFIG[level]
        level_dir = output_dir / dir_name
        level_dir.mkdir(parents=True, exist_ok=True)
        case_counter = 0

        for idx, golden in enumerate(golden_cases):
            case_counter += 1
            base_id: str = golden.get("id", f"UNKNOWN-{idx:03d}")
            clean_query: str = golden.get("query", "")

            # For jailbreak/injection, cycle template index per case
            if level in (AttackLevel.JAILBREAK, AttackLevel.INDIRECT_INJECTION):
                from .perturbations import (
                    INJECTION_TEMPLATES,
                    JAILBREAK_TEMPLATES,
                    indirect_injection,
                    jailbreak,
                )

                if level == AttackLevel.JAILBREAK:
                    attacked_query = jailbreak(
                        clean_query,
                        template_index=idx % len(JAILBREAK_TEMPLATES),
                    )
                else:
                    attacked_query = indirect_injection(
                        clean_query,
                        template_index=idx % len(INJECTION_TEMPLATES),
                    )
            else:
                attacked_query = _LEVEL_CONFIG[level][2](clean_query)

            adv_id = f"ADV-L{level}-{case_counter:03d}"
            case = AdversarialCase(
                id=adv_id,
                attack_level=int(level),
                attack_type=attack_type,
                base_case_id=base_id,
                clean_query=clean_query,
                attacked_query=attacked_query,
                expected_clean_has_caveat=True,
                notes=f"{attack_type} perturbation of {base_id}",
            )
            adversarial_cases.append(case)

            # Save YAML
            yaml_path = level_dir / f"{adv_id}.yaml"
            _save_case(case, yaml_path)

    return adversarial_cases


def _save_case(case: AdversarialCase, path: Path) -> None:
    """Serialize an AdversarialCase to a YAML file."""
    data = {
        "id": case.id,
        "attack_level": case.attack_level,
        "attack_type": case.attack_type,
        "base_case_id": case.base_case_id,
        "clean_query": case.clean_query,
        "attacked_query": case.attacked_query,
        "expected_clean_has_caveat": case.expected_clean_has_caveat,
        "notes": case.notes,
    }
    with path.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh, allow_unicode=True, default_flow_style=False)
