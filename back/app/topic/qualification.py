"""Deterministic holdout qualification for sequential Topic continuity."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


TopicQualificationSplit = Literal["training", "validation"]


class TopicContinuityObservation(BaseModel):
    """One human-labelled repeated detector decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(min_length=1, max_length=200)
    split: TopicQualificationSplit
    case_id: str = Field(min_length=1, max_length=200)
    repetition: int = Field(ge=1)
    window_size: int = Field(ge=1, le=10)
    current_message_index: int = Field(ge=0, le=9)
    expected_same_topic: bool
    semantic_score: float = Field(ge=0.0, le=1.0)
    prior_score: float | None = Field(default=None, ge=0.0, le=1.0)
    detected_topic: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def index_inside_window(self) -> "TopicContinuityObservation":
        if self.current_message_index >= self.window_size:
            raise ValueError("current_message_index must be inside the tested window.")
        return self


class TopicProbabilityMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    observations: int = Field(ge=0)
    positives: int = Field(ge=0)
    accuracy: float = Field(ge=0.0, le=1.0)
    balanced_accuracy: float = Field(ge=0.0, le=1.0)
    brier_score: float = Field(ge=0.0, le=1.0)
    log_loss: float = Field(ge=0.0)
    expected_calibration_error: float = Field(ge=0.0, le=1.0)


class TopicContinuityQualification(BaseModel):
    """Versioned report; only holdout-safe reports can be promoted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    threshold: float = Field(ge=0.0, le=1.0)
    training: TopicProbabilityMetrics
    validation: TopicProbabilityMetrics
    validation_prior: TopicProbabilityMetrics | None = None
    stability_rate: float = Field(ge=0.0, le=1.0)
    repeated_case_groups: int = Field(ge=0)
    window_accuracy: dict[int, float]
    position_accuracy: dict[str, float]
    promotable: bool
    blockers: tuple[str, ...] = ()


def _candidate_thresholds(values: list[float]) -> list[float]:
    ordered = sorted(set(values))
    candidates = {0.0, 0.5, 1.0, *ordered}
    candidates.update(
        (left + right) / 2.0 for left, right in zip(ordered, ordered[1:])
    )
    return sorted(candidates)


def _balanced_accuracy(
    observations: list[TopicContinuityObservation], threshold: float
) -> float:
    positives = [item for item in observations if item.expected_same_topic]
    negatives = [item for item in observations if not item.expected_same_topic]
    true_positive_rate = (
        sum(item.semantic_score >= threshold for item in positives) / len(positives)
        if positives
        else 0.0
    )
    true_negative_rate = (
        sum(item.semantic_score < threshold for item in negatives) / len(negatives)
        if negatives
        else 0.0
    )
    return (true_positive_rate + true_negative_rate) / 2.0


def _select_threshold(observations: list[TopicContinuityObservation]) -> float:
    ranked = sorted(
        _candidate_thresholds([item.semantic_score for item in observations]),
        key=lambda threshold: (
            -_balanced_accuracy(observations, threshold),
            abs(threshold - 0.5),
            threshold,
        ),
    )
    return ranked[0]


def _metrics(
    observations: list[TopicContinuityObservation],
    *,
    threshold: float,
    score_kind: Literal["semantic", "prior"] = "semantic",
) -> TopicProbabilityMetrics:
    pairs = [
        (
            item.expected_same_topic,
            item.semantic_score if score_kind == "semantic" else item.prior_score,
        )
        for item in observations
    ]
    usable = [(expected, score) for expected, score in pairs if score is not None]
    if not usable:
        return TopicProbabilityMetrics(
            observations=0,
            positives=0,
            accuracy=0.0,
            balanced_accuracy=0.0,
            brier_score=0.0,
            log_loss=0.0,
            expected_calibration_error=0.0,
        )
    labelled = [(expected, float(score)) for expected, score in usable]
    binary = [1.0 if expected else 0.0 for expected, _score in labelled]
    scores = [score for _expected, score in labelled]
    accuracy = sum(
        (score >= threshold) == expected for expected, score in labelled
    ) / len(labelled)
    brier = sum((score - expected) ** 2 for score, expected in zip(scores, binary)) / len(scores)
    epsilon = 1e-12
    log_loss = -sum(
        expected * math.log(max(epsilon, min(1.0 - epsilon, score)))
        + (1.0 - expected)
        * math.log(max(epsilon, min(1.0 - epsilon, 1.0 - score)))
        for score, expected in zip(scores, binary)
    ) / len(scores)
    calibration_error = 0.0
    for bucket in range(10):
        lower = bucket / 10.0
        upper = (bucket + 1) / 10.0
        bucket_pairs = [
            (expected, score)
            for expected, score in labelled
            if (
                lower <= score <= upper
                if bucket == 9
                else lower <= score < upper
            )
        ]
        if not bucket_pairs:
            continue
        observed = sum(expected for expected, _score in bucket_pairs) / len(bucket_pairs)
        confidence = sum(score for _expected, score in bucket_pairs) / len(bucket_pairs)
        calibration_error += len(bucket_pairs) / len(labelled) * abs(observed - confidence)
    positives = [(expected, score) for expected, score in labelled if expected]
    negatives = [(expected, score) for expected, score in labelled if not expected]
    true_positive_rate = (
        sum(score >= threshold for _expected, score in positives) / len(positives)
        if positives
        else 0.0
    )
    true_negative_rate = (
        sum(score < threshold for _expected, score in negatives) / len(negatives)
        if negatives
        else 0.0
    )
    return TopicProbabilityMetrics(
        observations=len(labelled),
        positives=sum(expected for expected, _score in labelled),
        accuracy=accuracy,
        balanced_accuracy=(true_positive_rate + true_negative_rate) / 2.0,
        brier_score=brier,
        log_loss=log_loss,
        expected_calibration_error=calibration_error,
    )


def _accuracy_by(
    observations: list[TopicContinuityObservation],
    threshold: float,
    keys: Sequence[int | str],
) -> dict[int | str, float]:
    grouped: dict[int | str, list[bool]] = defaultdict(list)
    for item, key in zip(observations, keys):
        grouped[key].append(
            (item.semantic_score >= threshold) == item.expected_same_topic
        )
    return {key: sum(values) / len(values) for key, values in grouped.items()}


def qualify_topic_continuity(
    observations: list[TopicContinuityObservation],
) -> TopicContinuityQualification:
    """Fit the threshold on training only and assess calibration on disjoint holdout."""

    training = [item for item in observations if item.split == "training"]
    validation = [item for item in observations if item.split == "validation"]
    if not training or not validation:
        raise ValueError("Training and validation observations are both required.")
    training_ids = {item.dataset_id for item in training}
    validation_ids = {item.dataset_id for item in validation}
    if training_ids & validation_ids:
        raise ValueError("Training and validation datasets must be disjoint.")
    threshold = _select_threshold(training)

    repeated: dict[tuple[str, str, int, int], list[str]] = defaultdict(list)
    for item in validation:
        repeated[
            (
                item.dataset_id,
                item.case_id,
                item.window_size,
                item.current_message_index,
            )
        ].append(item.detected_topic.casefold())
    repeated_groups = [values for values in repeated.values() if len(values) >= 2]
    stability = (
        sum(len(set(values)) == 1 for values in repeated_groups)
        / len(repeated_groups)
        if repeated_groups
        else 0.0
    )
    position_keys = [
        "start"
        if item.current_message_index == 0
        else "end"
        if item.current_message_index == item.window_size - 1
        else "middle"
        for item in validation
    ]
    blockers: list[str] = []
    if len(training) < 50 or len(validation) < 50:
        blockers.append("at_least_50_observations_per_split")
    if len({item.expected_same_topic for item in training}) < 2 or len(
        {item.expected_same_topic for item in validation}
    ) < 2:
        blockers.append("both_continuity_classes_per_split")
    if not {1, 5, 10}.issubset({item.window_size for item in validation}):
        blockers.append("window_sizes_1_5_10")
    if not {"start", "middle", "end"}.issubset(position_keys):
        blockers.append("window_positions_start_middle_end")
    if not repeated_groups or min(map(len, repeated_groups)) < 3:
        blockers.append("three_repetitions_per_stability_case")
    if stability < 0.95:
        blockers.append("stability_below_95_percent")

    fingerprint = hashlib.sha256(
        json.dumps(
            [item.model_dump(mode="json") for item in observations],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()[:16]
    prior_metrics = _metrics(validation, threshold=0.5, score_kind="prior")
    window_accuracy = _accuracy_by(
        validation,
        threshold,
        [item.window_size for item in validation],
    )
    position_accuracy = _accuracy_by(validation, threshold, position_keys)
    return TopicContinuityQualification(
        version=f"topic-continuity-qualification:v1:{fingerprint}",
        threshold=threshold,
        training=_metrics(training, threshold=threshold),
        validation=_metrics(validation, threshold=threshold),
        validation_prior=prior_metrics if prior_metrics.observations else None,
        stability_rate=stability,
        repeated_case_groups=len(repeated_groups),
        window_accuracy={int(key): value for key, value in window_accuracy.items()},
        position_accuracy={str(key): value for key, value in position_accuracy.items()},
        promotable=not blockers,
        blockers=tuple(blockers),
    )


__all__ = [
    "TopicContinuityObservation",
    "TopicContinuityQualification",
    "TopicProbabilityMetrics",
    "qualify_topic_continuity",
]
