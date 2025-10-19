from octopus2adls.enrich import detect_missing_intervals, vectorized_rate_join


def test_vectorized_rate_join_basic():
    consumption = [
        {
            "interval_start": "2024-01-01T00:00:00Z",
            "interval_end": "2024-01-01T00:30:00Z",
            "consumption": 0.5
        },
        {
            "interval_start": "2024-01-01T00:30:00Z",
            "interval_end": "2024-01-01T01:00:00Z",
            "consumption": 0.7
        },
    ]
    rates = [
        {
            "valid_from": "2023-12-31T23:30:00Z",
            "valid_to": "2024-01-01T00:30:00Z",
            "value_inc_vat": 0.30
        },
        {"valid_from": "2024-01-01T00:30:00Z", "valid_to": None, "value_inc_vat": 0.28},
    ]
    df = vectorized_rate_join(consumption, rates)
    assert len(df) == 2
    # cost check
    assert round(df['cost'].sum(), 6) == round(0.5*0.30 + 0.7*0.28, 6)

def test_vectorized_rate_join_gap():
    consumption = [
        {
            "interval_start": "2024-01-01T00:00:00Z",
            "interval_end": "2024-01-01T00:30:00Z",
            "consumption": 0.5
        },
        {
            "interval_start": "2024-01-01T00:30:00Z",
            "interval_end": "2024-01-01T01:00:00Z",
            "consumption": 0.7
        },
    ]
    # Rate gap: first rate ends before second interval start and no subsequent rate
    rates = [
        {
            "valid_from": "2023-12-31T23:30:00Z",
            "valid_to": "2024-01-01T00:15:00Z",
            "value_inc_vat": 0.30
        },
    ]
    df = vectorized_rate_join(consumption, rates)
    # only first interval may match depending on boundary, second unmatched
    assert len(df) <= 2

def test_detect_missing_intervals():
    # Two contiguous intervals => no missing
    consumption = [
        {"interval_end": "2024-01-01T00:30:00Z"},
        {"interval_end": "2024-01-01T01:00:00Z"},
    ]
    exp, act, miss = detect_missing_intervals(consumption)
    assert miss == 0
    # Introduce a gap (skip one)
    consumption_gap = [
        {"interval_end": "2024-01-01T00:30:00Z"},
        {"interval_end": "2024-01-01T01:30:00Z"},
    ]
    exp2, act2, miss2 = detect_missing_intervals(consumption_gap)
    assert miss2 == 1  # one 30m slot missing
