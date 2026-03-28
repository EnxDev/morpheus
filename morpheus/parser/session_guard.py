"""Cross-iteration anomaly detection for the clarification loop.

Tracks intent changes across clarification iterations and flags suspicious
patterns: drastic value changes, field drift, and escalation attacks.

The clarification loop is the most exposed attack surface because each
answer is a new input that modifies the intent. An attacker can craft
seemingly innocent answers that gradually shift the intent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from intent.schema import DynamicIntent


@dataclass
class SessionAnomaly:
    """A detected anomaly in the clarification session."""

    field: str
    anomaly_type: str  # "drastic_change" | "field_drift" | "confidence_spike"
    description: str


@dataclass
class SessionGuard:
    """Tracks intent evolution across clarification iterations.

    Create one per session. Call record_iteration() after each clarification.
    Call check_anomalies() to get a list of detected issues.
    """

    _history: list[dict] = field(default_factory=list)
    _max_iterations: int = 10

    def record_iteration(self, intent: DynamicIntent, field_updated: str, answer: str) -> None:
        """Record a clarification iteration."""
        self._history.append({
            "intent": intent.to_dict(),
            "field_updated": field_updated,
            "answer": answer,
            "iteration": len(self._history),
        })

    def check_anomalies(self) -> list[SessionAnomaly]:
        """Analyze the full history for suspicious patterns."""
        anomalies: list[SessionAnomaly] = []

        if len(self._history) < 2:
            return anomalies

        prev = self._history[-2]
        curr = self._history[-1]
        field_updated = curr["field_updated"]

        # 1. Drastic change: a field that was already resolved gets changed
        #    to something completely different
        prev_intent = prev["intent"]
        curr_intent = curr["intent"]

        for fname in prev_intent:
            if fname == field_updated:
                continue  # the updated field is expected to change
            prev_hyps = prev_intent.get(fname, [])
            curr_hyps = curr_intent.get(fname, [])
            if not prev_hyps or not curr_hyps:
                continue
            prev_val = prev_hyps[0].get("value")
            curr_val = curr_hyps[0].get("value")
            if prev_val and curr_val and prev_val != curr_val:
                anomalies.append(SessionAnomaly(
                    field=fname,
                    anomaly_type="field_drift",
                    description=f"Field '{fname}' changed from '{prev_val}' to '{curr_val}' "
                                f"without being the clarified field (was '{field_updated}')",
                ))

        # 2. Confidence spike: the updated field jumps from very low to very high
        #    in a way that seems artificial
        prev_field_hyps = prev_intent.get(field_updated, [])
        curr_field_hyps = curr_intent.get(field_updated, [])
        if prev_field_hyps and curr_field_hyps:
            prev_conf = prev_field_hyps[0].get("confidence", 0)
            curr_conf = curr_field_hyps[0].get("confidence", 0)
            # This is expected (clarification sets 0.95), but flag if the
            # answer itself looks suspicious (very short, or contains injection patterns)
            answer = curr["answer"]
            if curr_conf >= 0.9 and len(answer.strip()) <= 2:
                anomalies.append(SessionAnomaly(
                    field=field_updated,
                    anomaly_type="confidence_spike",
                    description=f"Field '{field_updated}' confidence jumped to {curr_conf} "
                                f"with a very short answer: '{answer}'",
                ))

        # 3. Same field clarified multiple times (potential manipulation)
        field_counts: dict[str, int] = {}
        for entry in self._history:
            f = entry["field_updated"]
            field_counts[f] = field_counts.get(f, 0) + 1
        for f, count in field_counts.items():
            if count >= 3:
                anomalies.append(SessionAnomaly(
                    field=f,
                    anomaly_type="repeated_clarification",
                    description=f"Field '{f}' has been clarified {count} times in this session",
                ))

        return anomalies

    def check_session_coherence(self, original_input: str) -> list[SessionAnomaly]:
        """Check if the final intent is still traceable to the original input
        and the set of user answers provided during clarification.

        This is the cumulative coherence check: it compares the intent at the
        end of the clarification loop against all legitimate sources of information
        (original query + all clarification answers), not just iteration-by-iteration.

        An attack that distributes a malicious intent across multiple innocent-looking
        answers will produce field values that cannot be traced to any single source.
        """
        if not self._history:
            return []

        anomalies: list[SessionAnomaly] = []
        current = self._history[-1]
        current_intent = current["intent"]

        # Build the full corpus of legitimate text: original input + all answers
        all_answers = [entry["answer"] for entry in self._history]
        corpus = (original_input + " " + " ".join(all_answers)).lower()
        corpus_tokens = set(
            token for token in corpus.split()
            if len(token) >= 2
        )

        for field_name, hypotheses in current_intent.items():
            if not hypotheses:
                continue
            top_value = hypotheses[0].get("value")
            if not top_value or not top_value.strip():
                continue

            val_lower = top_value.lower().strip()

            # Check 1: direct substring match in corpus
            if val_lower in corpus:
                continue

            # Check 2: token overlap — at least 50% of value tokens in corpus
            val_tokens = set(
                token for token in val_lower.split()
                if len(token) >= 2
            )
            if not val_tokens:
                continue

            overlap = val_tokens & corpus_tokens
            ratio = len(overlap) / len(val_tokens)
            if ratio >= 0.5:
                continue

            # Value not traceable to any legitimate source
            anomalies.append(SessionAnomaly(
                field=field_name,
                anomaly_type="cumulative_incoherence",
                description=(
                    f"Field '{field_name}' has value '{top_value}' which cannot be "
                    f"traced to the original input or any clarification answer"
                ),
            ))

        return anomalies

    @property
    def iteration_count(self) -> int:
        return len(self._history)

    @property
    def history(self) -> list[dict]:
        return list(self._history)
