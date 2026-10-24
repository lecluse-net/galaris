"""Repeated measurements do not manufacture independent evidence."""

from app.lab.statistics import estimate


def test_case_weighting_and_intervals_preserve_repetition_clusters():
    original = estimate([[0], [100]])
    repeated = estimate([[0] * 100, [100]])
    assert repeated.mean == original.mean == 50
    assert (repeated.lower, repeated.upper) == (original.lower, original.upper)
    assert repeated.cases == 2 and repeated.observations == 101
    assert not repeated.sufficient
    single = estimate([[50] * 100])
    assert single.cases == 1 and single.lower is None and single.upper is None
    assert estimate([]).mean is None
    assert estimate([[float('nan')]]).cases == 0


def test_no_observed_false_pass_still_has_uncertainty():
    result = estimate([[0] for _ in range(20)], bounds=(0, 100))
    assert result.sufficient and result.mean == result.lower == 0
    assert 0 < result.upper < 100
    assert result.method == 'case-cluster-hoeffding/v1' and result.resamples == 0
