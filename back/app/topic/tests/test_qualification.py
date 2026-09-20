from __future__ import annotations

import pytest

from app.topic.qualification import (
    TopicContinuityObservation,
    qualify_topic_continuity,
)


def _observation(
    *,
    split: str,
    dataset_id: str,
    case: int,
    repetition: int,
    window_size: int,
    current_index: int,
) -> TopicContinuityObservation:
    expected = case % 2 == 0
    return TopicContinuityObservation(
        dataset_id=dataset_id,
        split=split,
        case_id=f"case-{case}",
        repetition=repetition,
        window_size=window_size,
        current_message_index=current_index,
        expected_same_topic=expected,
        semantic_score=0.9 if expected else 0.1,
        prior_score=0.65 if expected else 0.35,
        detected_topic="Topic A" if expected else f"Topic B {case}",
    )


def test_qualification_uses_disjoint_holdout_stability_and_window_coverage() -> None:
    training = [
        _observation(
            split="training",
            dataset_id="human-training-v1",
            case=case,
            repetition=1,
            window_size=10,
            current_index=9,
        )
        for case in range(60)
    ]
    shapes = ((1, 0), (5, 2), (10, 9))
    validation = [
        _observation(
            split="validation",
            dataset_id="human-holdout-v1",
            case=case,
            repetition=repetition,
            window_size=shapes[case % len(shapes)][0],
            current_index=shapes[case % len(shapes)][1],
        )
        for case in range(20)
        for repetition in range(1, 4)
    ]

    report = qualify_topic_continuity([*training, *validation])

    assert report.promotable
    assert report.blockers == ()
    assert report.threshold == 0.5
    assert report.training.accuracy == 1.0
    assert report.validation.accuracy == 1.0
    assert report.stability_rate == 1.0
    assert report.repeated_case_groups == 20
    assert set(report.window_accuracy) == {1, 5, 10}
    assert set(report.position_accuracy) == {"start", "middle", "end"}
    assert report.validation_prior is not None
    assert report.version.startswith("topic-continuity-qualification:v1:")


def test_qualification_refuses_train_holdout_overlap() -> None:
    observations = [
        _observation(
            split=split,
            dataset_id="same-dataset",
            case=index,
            repetition=1,
            window_size=1,
            current_index=0,
        )
        for index, split in enumerate(("training", "validation"))
    ]

    with pytest.raises(ValueError, match="must be disjoint"):
        qualify_topic_continuity(observations)
