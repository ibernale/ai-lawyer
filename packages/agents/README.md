# packages/agents

Orchestrator-worker agent hierarchy for lex-agents. Contains the router agent
(classifies queries by legal domain), specialist agents (one per branch of law;
MVP: `regulatorio_bancario_ue_es`), and the synthesizer agent (merges
specialist outputs into a single cited response). Uses Anthropic API with
versioned system prompts loaded from `docs/prompts/`.
