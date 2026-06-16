"""Agent identifiers and shared static strings for backend orchestration."""
from __future__ import annotations

AGENT_RECEPTIONIST = "receptionist"
AGENT_SUPPORT = "support"
AGENT_PURPOSE_TUNER = "purpose_tuner"
AGENT_OPTIMIZER = "optimizer"
AGENT_REVIEWER = "reviewer"

PURPOSE_OPTIONS = [
    "Improving study design",
    "Enhanced safety signal interpretation",
    "Reducing the size of the control arm",
    "Precision powering by minimizing missing data",
    "Inclusion/exclusion criteria optimization",
    "Clinical feasibility optimization",
    "Biomarker development",
    "Publication or presentation",
    "Submission to IRB or regulatory agency",
]

PURPOSE_TUNER_CAPTURE_PROMPT = (
    "Great — tell me about the diseases, medication, product development, and therapeutic area."
)

FALLBACK_RESPONSE = (
    "I ran into an issue interpreting that. "
    "Could you rephrase the details about the diseases, medication, "
    "product development, and therapeutic area?"
)

AGENT_DESCRIPTIONS = {
    AGENT_RECEPTIONIST: "Tells you how things work and where to get information",
    AGENT_SUPPORT: "Search for existing knowledge, documentation, and tool guidance",
    AGENT_PURPOSE_TUNER: "Helps find and properly form optimal research purposes",
    AGENT_OPTIMIZER: "Recognize existing use cases and avoid redundancy",
    AGENT_REVIEWER: "Validates purposes for DDO review against study descriptors",
}
