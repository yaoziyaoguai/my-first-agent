"""Runtime-owned closed evidence oracles built only from durable raw facts."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from agent.runtime.contracts import (
    AdmittedCriterion,
    CitationManifestV1,
    CompletionClaim,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    EvidenceOracleKind,
    EvidenceRecord,
    FactKind,
    ProcessReceiptV1,
    SourceKind,
    SourceReceiptV1,
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
        if (
            any(target.endswith(".citations.json") for target in goal.targets)
            and not any(
                item.oracle_kind is EvidenceOracleKind.RESEARCH_PROVENANCE
                for item in mandatory
            )
        ):
            raise EvidenceVerificationError(
                "citation sidecar target requires admitted research provenance"
            )
        web_requirements = {
            item.criterion_id
            for item in goal.proposed_criteria
            if item.oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT
        }
        admitted_web = {
            item.criterion_id
            for item in mandatory
            if item.oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT
        }
        if not web_requirements.issubset(admitted_web):
            raise EvidenceVerificationError(
                "public Web requirement has no admitted source receipt"
            )
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
            elif criterion.oracle_kind is EvidenceOracleKind.RESEARCH_PROVENANCE:
                derived = self._research_provenance(
                    state,
                    criterion=criterion,
                    evidence_id=evidence_id,
                    observed_at=evidence_observed_at,
                )
            elif criterion.oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT:
                derived = self._web_source_receipt(
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

    def _web_source_receipt(
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
        expected_digest = predicate.get("receipt_digest")
        expected_kind = predicate.get("source_kind")
        if set(predicate) != {"receipt_digest", "source_kind"} or expected_kind not in {
            SourceKind.WEB_SEARCH_SNIPPET.value,
            SourceKind.WEB_EXTRACTED_CONTENT.value,
        }:
            raise EvidenceVerificationError("public Web source predicate is invalid")
        source: list[ConversationFact] = []
        for fact in facts:
            metadata = fact.content.get("metadata")
            if (
                fact.kind is not FactKind.TOOL_RESULT
                or fact.content.get("executed") is not True
                or fact.content.get("is_error") is not False
                or not isinstance(metadata, dict)
                or metadata.get("fake")
                or metadata.get("mock")
            ):
                continue
            raw_receipts = metadata.get("source_receipts")
            if not isinstance(raw_receipts, list):
                continue
            for raw in raw_receipts:
                try:
                    receipt = SourceReceiptV1.from_json(raw)
                except ValueError:
                    continue
                if (
                    receipt.receipt_digest == expected_digest
                    and receipt.source_kind.value == expected_kind
                    and receipt.goal_id == goal_id
                    and receipt.goal_revision is not None
                    and receipt.goal_revision <= goal_revision
                ):
                    source.append(fact)
                    break
        if not source:
            raise EvidenceVerificationError(
                "no exact public Web source receipt proves the criterion"
            )
        return self._record(
            source[:1],
            goal_id=goal_id,
            goal_revision=goal_revision,
            criterion=criterion,
            evidence_id=evidence_id,
            oracle_identity="public-web-source-receipt:v1",
            observed_at=observed_at,
        )

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

    def _research_provenance(
        self,
        state: ConversationState,
        *,
        criterion: AdmittedCriterion,
        evidence_id: str,
        observed_at: str,
    ) -> EvidenceRecord:
        """从当前 Goal 的原始 receipts 和 exact read-back 重建研究交付证据。"""

        goal = state.goal
        if goal is None:
            raise EvidenceVerificationError("research provenance requires a current Goal")
        predicate = criterion.predicate
        required_keys = {
            "artifact_path",
            "artifact_sha256",
            "manifest_path",
            "manifest_sha256",
            "manifest_digest",
            "minimum_distinct_sources",
            "required_source_kinds",
            "required_source_classes",
            "required_receipt_digests",
        }
        optional_keys = {"observed_after", "maximum_age_seconds"}
        if not required_keys.issubset(predicate) or not set(predicate).issubset(
            required_keys | optional_keys
        ):
            raise EvidenceVerificationError("research provenance predicate must be exact")
        artifact_path = self._predicate_text(predicate, "artifact_path")
        artifact_digest = self._predicate_digest(predicate, "artifact_sha256")
        manifest_path = self._predicate_text(predicate, "manifest_path")
        manifest_sha = self._predicate_digest(predicate, "manifest_sha256")
        manifest_digest = self._predicate_digest(predicate, "manifest_digest")
        minimum_sources = predicate["minimum_distinct_sources"]
        if (
            not isinstance(minimum_sources, int)
            or isinstance(minimum_sources, bool)
            or not 1 <= minimum_sources <= 16
        ):
            raise EvidenceVerificationError("distinct source requirement is malformed")
        required_kinds = self._predicate_text_sequence(
            predicate, "required_source_kinds"
        )
        required_classes = self._predicate_text_sequence(
            predicate, "required_source_classes"
        )
        required_receipts = self._predicate_text_sequence(
            predicate, "required_receipt_digests"
        )
        if any(
            len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in required_receipts
        ):
            raise EvidenceVerificationError("required receipt digest is malformed")
        if (
            not manifest_path.endswith(".citations.json")
            or manifest_path == artifact_path
            or manifest_path not in goal.targets
            or artifact_path not in goal.targets
        ):
            raise EvidenceVerificationError("citation manifest path is not bound to artifact")

        artifact_call, artifact_result, artifact = self._exact_readback(
            state.facts, artifact_path, artifact_digest
        )
        manifest_call, manifest_result, manifest_raw = self._exact_readback(
            state.facts, manifest_path, manifest_sha
        )
        try:
            manifest = CitationManifestV1.from_json(manifest_raw)
        except ValueError as error:
            raise EvidenceVerificationError(
                "citation manifest read-back is invalid"
            ) from error
        if (
            manifest.goal_id != goal.goal_id
            or manifest.goal_revision != goal.revision
        ):
            raise EvidenceVerificationError(
                "citation manifest is not bound to the current Goal"
            )
        if (
            manifest.artifact_path != artifact_path
            or manifest.artifact_sha256 != artifact_digest
            or manifest.manifest_digest != manifest_digest
        ):
            raise EvidenceVerificationError(
                "citation manifest is not bound to the exact artifact"
            )

        receipts = self._source_receipts(state.facts)
        cited: list[tuple[SourceReceiptV1, ConversationFact]] = []
        for citation in manifest.citations:
            matched = receipts.get((citation.source_id, citation.receipt_digest))
            if matched is None:
                raise EvidenceVerificationError(
                    "citation has no exact Runtime-issued source receipt"
                )
            receipt, fact, untrusted = matched
            if untrusted:
                raise EvidenceVerificationError("fake source receipt cannot prove research")
            if (
                receipt.conversation_id != state.conversation_id
                or receipt.goal_id != goal.goal_id
                or receipt.goal_revision != goal.revision
            ):
                raise EvidenceVerificationError(
                    "source receipt is not bound to the current Goal"
                )
            if receipt.truncated:
                raise EvidenceVerificationError(
                    "truncated source receipt cannot prove research"
                )
            if citation.marker not in artifact:
                raise EvidenceVerificationError(
                    "each citation marker must occur in the artifact"
                )
            cited.append((receipt, fact))

        distinct_source_ids = {receipt.source_id for receipt, _fact in cited}
        if len(distinct_source_ids) < minimum_sources:
            raise EvidenceVerificationError("distinct source requirement is not met")
        cited_kinds = {receipt.source_kind.value for receipt, _fact in cited}
        if not set(required_kinds).issubset(cited_kinds):
            raise EvidenceVerificationError("required source kind is not cited")
        if SourceKind.WEB_SEARCH_SNIPPET.value in cited_kinds:
            raise EvidenceVerificationError(
                "required source kind must contain extracted web content, not a search snippet"
            )
        cited_classes = {
            source_class
            for receipt, _fact in cited
            for source_class in self._source_classes(receipt)
        }
        if not set(required_classes).issubset(cited_classes):
            raise EvidenceVerificationError("required source class is not cited")
        cited_digests = {receipt.receipt_digest for receipt, _fact in cited}
        if not set(required_receipts).issubset(cited_digests):
            raise EvidenceVerificationError("required source receipt is not cited")

        cited_web_urls = {
            receipt.origin_locator
            for receipt, _fact in cited
            if receipt.source_kind.value.startswith("web_")
        }
        artifact_urls = {
            value.rstrip(".,;:!?")
            for value in re.findall(r"https?://[^\s<>\]\)}]+", artifact)
        }
        if not artifact_urls.issubset(cited_web_urls):
            raise EvidenceVerificationError("artifact contains an invented URL")

        self._verify_freshness(
            tuple(receipt for receipt, _fact in cited),
            predicate=predicate,
            observed_at=observed_at,
        )
        source: list[ConversationFact] = [
            artifact_call,
            artifact_result,
            manifest_call,
            manifest_result,
        ]
        source.extend(fact for _receipt, fact in cited)
        unique_source = list({fact.fact_id: fact for fact in source}.values())
        return self._record(
            unique_source,
            goal_id=goal.goal_id,
            goal_revision=goal.revision,
            criterion=criterion,
            evidence_id=evidence_id,
            oracle_identity="research-provenance:v1",
            observed_at=observed_at,
        )

    @staticmethod
    def _predicate_text(predicate, key: str) -> str:  # noqa: ANN001
        value = predicate.get(key)
        if not isinstance(value, str) or not value:
            raise EvidenceVerificationError(f"research predicate {key} is malformed")
        return value

    @classmethod
    def _predicate_digest(cls, predicate, key: str) -> str:  # noqa: ANN001
        value = cls._predicate_text(predicate, key)
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise EvidenceVerificationError(f"research predicate {key} is malformed")
        return value

    @staticmethod
    def _predicate_text_sequence(predicate, key: str) -> tuple[str, ...]:  # noqa: ANN001
        value = predicate.get(key)
        if not isinstance(value, (list, tuple)) or any(
            not isinstance(item, str) or not item for item in value
        ):
            raise EvidenceVerificationError(f"research predicate {key} is malformed")
        return tuple(value)

    @classmethod
    def _exact_readback(
        cls,
        facts: tuple[ConversationFact, ...],
        path: str,
        expected_digest: str,
    ) -> tuple[ConversationFact, ConversationFact, str]:
        calls = cls._calls(facts)
        for fact in reversed(facts):
            if fact.kind is not FactKind.TOOL_RESULT:
                continue
            call_id = fact.content.get("tool_call_id")
            call = calls.get(call_id) if isinstance(call_id, str) else None
            if call is None or call.get("name") != "read_file":
                continue
            arguments = call.get("arguments")
            if not isinstance(arguments, dict) or arguments.get("path") != path:
                continue
            metadata = fact.content.get("metadata")
            if (
                fact.content.get("is_error") is not False
                or fact.content.get("executed") is not True
                or fact.content.get("synthetic") is True
                or (
                    isinstance(metadata, dict)
                    and (metadata.get("fake") or metadata.get("mock") or metadata.get("synthetic"))
                )
            ):
                continue
            text = fact.content.get("text")
            if (
                isinstance(text, str)
                and hashlib.sha256(text.encode("utf-8")).hexdigest() == expected_digest
            ):
                return call["fact"], fact, text
        raise EvidenceVerificationError(
            "no exact read-back fact proves the research artifact"
        )

    @staticmethod
    def _source_receipts(
        facts: tuple[ConversationFact, ...],
    ) -> dict[tuple[str, str], tuple[SourceReceiptV1, ConversationFact, bool]]:
        result: dict[
            tuple[str, str], tuple[SourceReceiptV1, ConversationFact, bool]
        ] = {}
        for fact in facts:
            if (
                fact.kind is not FactKind.TOOL_RESULT
                or fact.content.get("is_error") is not False
                or fact.content.get("executed") is not True
                or fact.content.get("synthetic") is True
            ):
                continue
            metadata = fact.content.get("metadata")
            if not isinstance(metadata, dict):
                continue
            raw_receipts = metadata.get("source_receipts")
            if not isinstance(raw_receipts, list):
                continue
            untrusted = bool(
                metadata.get("fake") or metadata.get("mock") or metadata.get("synthetic")
            )
            for raw_receipt in raw_receipts:
                try:
                    receipt = SourceReceiptV1.from_json(raw_receipt)
                except ValueError:
                    continue
                result[(receipt.source_id, receipt.receipt_digest)] = (
                    receipt,
                    fact,
                    untrusted,
                )
        return result

    @staticmethod
    def _source_classes(receipt: SourceReceiptV1) -> tuple[str, ...]:
        value = receipt.source_kind.value
        classes = [receipt.data_class]
        if value.startswith("history_"):
            classes.append("history")
        if value.startswith("workspace_"):
            classes.append("workspace")
        if value.startswith("web_"):
            classes.append("web")
        return tuple(classes)

    @classmethod
    def _verify_freshness(
        cls,
        receipts: tuple[SourceReceiptV1, ...],
        *,
        predicate,
        observed_at: str,
    ) -> None:  # noqa: ANN001
        web_receipts = tuple(
            receipt
            for receipt in receipts
            if receipt.source_kind.value.startswith("web_")
        )
        observed_after = predicate.get("observed_after")
        if observed_after is not None:
            if not isinstance(observed_after, str):
                raise EvidenceVerificationError("freshness boundary is malformed")
            boundary = cls._timestamp(observed_after)
            if any(cls._timestamp(receipt.observed_at) < boundary for receipt in web_receipts):
                raise EvidenceVerificationError("web source freshness requirement is not met")
        maximum_age = predicate.get("maximum_age_seconds")
        if maximum_age is not None:
            if (
                not isinstance(maximum_age, int)
                or isinstance(maximum_age, bool)
                or maximum_age < 0
            ):
                raise EvidenceVerificationError("freshness maximum age is malformed")
            now = cls._timestamp(observed_at)
            if any(
                (now - cls._timestamp(receipt.observed_at)).total_seconds() > maximum_age
                for receipt in web_receipts
            ):
                raise EvidenceVerificationError("web source freshness requirement is not met")

    @staticmethod
    def _timestamp(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError) as error:
            raise EvidenceVerificationError("freshness timestamp is malformed") from error
        if parsed.tzinfo is None:
            raise EvidenceVerificationError("freshness timestamp must include timezone")
        return parsed

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
            if not isinstance(metadata, dict) or metadata.get("fake") or metadata.get("mock"):
                continue
            proved = False
            raw_receipts = metadata.get("source_receipts")
            if isinstance(raw_receipts, (list, tuple)):
                for raw_receipt in raw_receipts:
                    try:
                        receipt = SourceReceiptV1.from_json(raw_receipt)
                    except ValueError:
                        continue
                    if (
                        receipt.source_kind is SourceKind.WORKSPACE_EXCERPT
                        and receipt.origin_locator == path
                        and receipt.original_content_digest == expected_digest
                        and receipt.goal_id == goal_id
                        and receipt.goal_revision == goal_revision
                        and not receipt.truncated
                    ):
                        proved = True
                        break
            # 012-014 legacy text read-back 没有 source receipt；保持精确 UTF-8 digest
            # 兼容。015+ binary/replacement-decoded artifact 则由 original bytes digest 证明。
            text = fact.content.get("text")
            if (
                not proved
                and isinstance(text, str)
                and hashlib.sha256(text.encode("utf-8")).hexdigest() == expected_digest
            ):
                proved = True
            if not proved:
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
        if criterion.predicate.get("receipt_kind") == "process_v1":
            return self._process_tool_receipt(
                facts,
                criterion=criterion,
                goal_id=goal_id,
                goal_revision=goal_revision,
                evidence_id=evidence_id,
                observed_at=observed_at,
            )
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

    def _process_tool_receipt(
        self,
        facts: tuple[ConversationFact, ...],
        *,
        criterion: AdmittedCriterion,
        goal_id: str,
        goal_revision: int,
        evidence_id: str,
        observed_at: str,
    ) -> EvidenceRecord:
        """015 加式 process predicate（§11）。closed allowlist；legacy 单键不受影响。"""

        predicate = criterion.predicate
        allowed = {
            "receipt_kind",
            "receipt_digest",
            "command_fingerprint",
            "outcome",
            "exit_code",
            "stdout_digest",
            "stderr_digest",
        }
        unknown = set(predicate) - allowed
        if unknown:
            raise EvidenceVerificationError(
                "process receipt predicate has unknown keys"
            )
        if predicate.get("receipt_kind") != "process_v1":
            raise EvidenceVerificationError("process receipt kind mismatch")
        expected_digest = predicate.get("receipt_digest")
        expected_outcome = predicate.get("outcome")
        expected_fingerprint = predicate.get("command_fingerprint")
        if not (
            isinstance(expected_outcome, str)
            and isinstance(expected_fingerprint, str)
        ):
            raise EvidenceVerificationError("process receipt predicate must be complete")
        if expected_digest is not None and (
            not isinstance(expected_digest, str)
            or len(expected_digest) != 64
            or any(c not in "0123456789abcdef" for c in expected_digest)
        ):
            raise EvidenceVerificationError(
                "process receipt predicate receipt_digest must be 64 lowercase hex"
            )
        requires_exit_code = expected_outcome == "exited"
        expected_exit_code = predicate.get("exit_code")
        if requires_exit_code:
            if not isinstance(expected_exit_code, int) or isinstance(
                expected_exit_code, bool
            ):
                raise EvidenceVerificationError(
                    "exited process receipt predicate requires an integer exit_code"
                )
        elif "exit_code" in predicate:
            raise EvidenceVerificationError(
                "non-exited process receipt predicate must not pin exit_code"
            )
        # P3（冻结合同）：声明的 optional stdout/stderr digests 必须实际比较——
        # 此前 allowlist 接受却从不检查（空证据通过）。
        digest_expectations: dict[str, str] = {}
        for label in ("stdout_digest", "stderr_digest"):
            if label not in predicate:
                continue
            expected_output_digest = predicate[label]
            if (
                not isinstance(expected_output_digest, str)
                or len(expected_output_digest) != 64
                or any(c not in "0123456789abcdef" for c in expected_output_digest)
            ):
                raise EvidenceVerificationError(
                    f"process receipt predicate {label} must be 64 lowercase hex"
                )
            digest_expectations[label] = expected_output_digest
        source: list[ConversationFact] = []
        for fact in facts:
            metadata = fact.content.get("metadata")
            if (
                fact.kind is not FactKind.TOOL_RESULT
                or fact.content.get("is_error") is True
                or not isinstance(metadata, dict)
                or metadata.get("fake")
                or metadata.get("mock")
            ):
                continue
            try:
                receipt = ProcessReceiptV1.from_json(
                    metadata.get("process_receipt")
                )
            except ValueError:
                continue
            # 完整 canonical receipt 是证据本体；扁平字段只是 UI/oracle projection，
            # 两者必须逐项一致，不能让 producer 拼一个看似可信的 metadata map。
            projection = {
                "process_receipt_kind": "process_v1",
                "receipt_digest": receipt.receipt_digest,
                "execution_authority": receipt.execution_authority.value,
                "outcome": receipt.outcome.value,
                "exit_code": receipt.exit_code,
                "command_fingerprint": receipt.command_fingerprint,
                "stdout_truncated": receipt.stdout_truncated,
                "stderr_truncated": receipt.stderr_truncated,
                "duration_seconds": receipt.duration_seconds,
                "resource_profile": receipt.resource_profile,
                "stdout_digest": receipt.stdout_digest,
                "stderr_digest": receipt.stderr_digest,
                "lease_id": receipt.lease_id,
                "use_ordinal": receipt.use_ordinal,
                "tool_identity": receipt.tool_identity,
            }
            if any(metadata.get(key) != value for key, value in projection.items()):
                continue
            if (
                receipt.goal_id != goal_id
                or receipt.goal_revision != goal_revision
                or (
                    expected_digest is not None
                    and receipt.receipt_digest != expected_digest
                )
                or receipt.outcome.value != expected_outcome
                or receipt.command_fingerprint != expected_fingerprint
                or (requires_exit_code and receipt.exit_code != expected_exit_code)
                or any(
                    getattr(receipt, label) != expected_output_digest
                    for label, expected_output_digest in digest_expectations.items()
                )
            ):
                continue
            source.append(fact)
        if not source:
            raise EvidenceVerificationError(
                "no exact process receipt proves the criterion"
            )
        return self._record(
            source[:1],
            goal_id=goal_id,
            goal_revision=goal_revision,
            criterion=criterion,
            evidence_id=evidence_id,
            oracle_identity="process-receipt:v1",
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
