"""Runtime-owned closed evidence oracles built only from durable raw facts."""

from __future__ import annotations

import hashlib

from agent.runtime.contracts import (
    AdmittedCriterion,
    CompletionClaim,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    EvidenceOracleKind,
    EvidenceRecord,
    FactKind,
    canonical_json_digest,
    closed_evidence_id,
)


class EvidenceVerificationError(ValueError):
    pass


class ClosedEvidenceRegistry:
    identity = "closed-evidence-registry-v1"

    def derive(
        self,
        state: ConversationState,
        claim: CompletionClaim,
        *,
        observed_at: str,
    ) -> tuple[EvidenceRecord, ...]:
        goal = state.goal
        if goal is None or claim.goal_id != goal.goal_id or claim.goal_revision != goal.revision:
            raise EvidenceVerificationError("completion claim is stale")
        mandatory = tuple(item for item in goal.admitted_criteria if item.mandatory)
        if not mandatory:
            raise EvidenceVerificationError("goal has no mandatory criterion")
        if (
            state.active_run is not None
            and state.active_run.phase is ContinuationPhase.EXECUTING
        ):
            raise EvidenceVerificationError("unknown effect blocks completion evidence")
        expected_ids = tuple(
            self.evidence_id(goal.goal_id, goal.revision, item.criterion_id)
            for item in mandatory
        )
        if tuple(claim.criterion_evidence_refs) != expected_ids:
            raise EvidenceVerificationError("completion claim evidence refs are not exact")

        existing = {record.evidence_id: record for record in state.evidence_records}
        records: list[EvidenceRecord] = []
        for criterion, evidence_id in zip(mandatory, expected_ids, strict=True):
            existing_record = existing.get(evidence_id)
            evidence_observed_at = (
                existing_record.observed_at
                if existing_record is not None
                else observed_at
            )
            if criterion.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST:
                derived = self._filesystem_digest(
                    state.facts,
                    goal_id=goal.goal_id,
                    goal_revision=goal.revision,
                    criterion=criterion,
                    evidence_id=evidence_id,
                    observed_at=evidence_observed_at,
                )
            elif criterion.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT:
                derived = self._tool_receipt(
                    state.facts,
                    goal_id=goal.goal_id,
                    goal_revision=goal.revision,
                    criterion=criterion,
                    evidence_id=evidence_id,
                    observed_at=evidence_observed_at,
                )
            elif criterion.oracle_kind is EvidenceOracleKind.USER_CONFIRMATION:
                derived = self._user_confirmation(
                    state.facts,
                    goal_id=goal.goal_id,
                    goal_revision=goal.revision,
                    criterion=criterion,
                    evidence_id=evidence_id,
                    observed_at=evidence_observed_at,
                )
            else:
                raise EvidenceVerificationError("criterion uses an unsupported oracle")
            if existing_record is not None and existing_record != derived:
                raise EvidenceVerificationError("stored evidence does not match raw durable facts")
            records.append(derived)
        return tuple(records)

    def _user_confirmation(
        self,
        facts: tuple[ConversationFact, ...],
        *,
        goal_id: str,
        goal_revision: int,
        criterion: AdmittedCriterion,
        evidence_id: str,
        observed_at: str,
    ) -> EvidenceRecord:
        source = [
            fact
            for fact in facts
            if fact.kind is FactKind.USER_MESSAGE
            and fact.content.get("criterion_id") == criterion.criterion_id
            and fact.content.get("confirmed") is True
        ]
        if not source:
            raise EvidenceVerificationError(
                "criterion requires exact user confirmation"
            )
        return self._record(
            source[-1:],
            goal_id=goal_id,
            goal_revision=goal_revision,
            criterion=criterion,
            evidence_id=evidence_id,
            oracle_identity="user-confirmation:v1",
            observed_at=observed_at,
        )

    @staticmethod
    def evidence_id(goal_id: str, goal_revision: int, criterion_id: str) -> str:
        return closed_evidence_id(goal_id, goal_revision, criterion_id)

    def _filesystem_digest(
        self,
        facts: tuple[ConversationFact, ...],
        *,
        goal_id: str,
        goal_revision: int,
        criterion: AdmittedCriterion,
        evidence_id: str,
        observed_at: str,
    ) -> EvidenceRecord:
        predicate = criterion.predicate
        if set(predicate) != {"path", "sha256"}:
            raise EvidenceVerificationError("filesystem predicate must be exact")
        path = predicate.get("path")
        expected_digest = predicate.get("sha256")
        if not isinstance(path, str) or not path or not isinstance(expected_digest, str):
            raise EvidenceVerificationError("filesystem predicate is malformed")
        calls = self._calls(facts)
        source: list[ConversationFact] = []
        for fact in facts:
            if fact.kind is not FactKind.TOOL_RESULT:
                continue
            call_id = fact.content.get("tool_call_id")
            call = calls.get(call_id) if isinstance(call_id, str) else None
            if call is None or call.get("name") != "read_file":
                continue
            arguments = call.get("arguments")
            if not isinstance(arguments, dict) or arguments.get("path") != path:
                continue
            if fact.content.get("is_error") is True or fact.content.get("executed") is False:
                continue
            metadata = fact.content.get("metadata")
            if isinstance(metadata, dict) and (metadata.get("fake") or metadata.get("mock")):
                continue
            text = fact.content.get("text")
            if not isinstance(text, str):
                continue
            if hashlib.sha256(text.encode("utf-8")).hexdigest() != expected_digest:
                continue
            source.extend((call["fact"], fact))
            break
        if not source:
            raise EvidenceVerificationError(
                "no exact read-back fact proves the filesystem criterion"
            )
        return self._record(
            source,
            goal_id=goal_id,
            goal_revision=goal_revision,
            criterion=criterion,
            evidence_id=evidence_id,
            oracle_identity="filesystem-digest:v1",
            observed_at=observed_at,
        )

    def _tool_receipt(
        self,
        facts: tuple[ConversationFact, ...],
        *,
        goal_id: str,
        goal_revision: int,
        criterion: AdmittedCriterion,
        evidence_id: str,
        observed_at: str,
    ) -> EvidenceRecord:
        expected = criterion.predicate.get("receipt_digest")
        if set(criterion.predicate) != {"receipt_digest"} or not isinstance(expected, str):
            raise EvidenceVerificationError("tool receipt predicate must be exact")
        source = [
            fact
            for fact in facts
            if fact.kind is FactKind.TOOL_RESULT
            and fact.content.get("is_error") is not True
            and isinstance(fact.content.get("metadata"), dict)
            and fact.content["metadata"].get("receipt_digest") == expected
            and not fact.content["metadata"].get("fake")
            and not fact.content["metadata"].get("mock")
        ]
        if not source:
            raise EvidenceVerificationError("no exact governed receipt proves the criterion")
        return self._record(
            source[:1],
            goal_id=goal_id,
            goal_revision=goal_revision,
            criterion=criterion,
            evidence_id=evidence_id,
            oracle_identity="tool-receipt:v1",
            observed_at=observed_at,
        )

    @staticmethod
    def _calls(facts: tuple[ConversationFact, ...]) -> dict[str, dict]:
        calls: dict[str, dict] = {}
        for fact in facts:
            if fact.kind is not FactKind.TOOL_CALLS:
                continue
            raw_calls = fact.content.get("calls")
            if not isinstance(raw_calls, list):
                continue
            for raw in raw_calls:
                if isinstance(raw, dict) and isinstance(raw.get("tool_call_id"), str):
                    calls[raw["tool_call_id"]] = {**raw, "fact": fact}
        return calls

    @staticmethod
    def _record(
        source: list[ConversationFact],
        *,
        goal_id: str,
        goal_revision: int,
        criterion: AdmittedCriterion,
        evidence_id: str,
        oracle_identity: str,
        observed_at: str,
    ) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id=evidence_id,
            goal_id=goal_id,
            goal_revision=goal_revision,
            criterion_id=criterion.criterion_id,
            oracle_kind=criterion.oracle_kind,
            predicate_digest=canonical_json_digest(criterion.predicate),
            source_fact_ids=tuple(fact.fact_id for fact in source),
            source_digest=canonical_json_digest(
                [
                    {"fact_id": fact.fact_id, "kind": fact.kind, "content": fact.content}
                    for fact in source
                ]
            ),
            oracle_identity=oracle_identity,
            passed=True,
            observed_at=observed_at,
        )
