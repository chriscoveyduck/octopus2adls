from __future__ import annotations
import pandas as pd
from typing import List, Dict, Tuple

def vectorized_rate_join(consumption: List[Dict], rates: List[Dict]) -> pd.DataFrame:
    """Join unit rates to consumption intervals using searchsorted on valid_from.

    Assumptions: consumption intervals are half-hour, non-overlapping, UTC times.
    Rate chosen where interval_start in [valid_from, valid_to) (treat null valid_to as open-ended).
    """
    if not consumption:
        return pd.DataFrame()
    df_c = pd.DataFrame(consumption).copy()
    if 'interval_start' not in df_c.columns:
        # derive interval_start assuming fixed length (30m) from end
        df_c['interval_end'] = pd.to_datetime(df_c['interval_end'], utc=True)
        df_c['interval_start'] = df_c['interval_end'] - pd.Timedelta(minutes=30)
    else:
        df_c['interval_start'] = pd.to_datetime(df_c['interval_start'], utc=True)
        df_c['interval_end'] = pd.to_datetime(df_c['interval_end'], utc=True)
    if not rates:
        return df_c
    df_r = pd.DataFrame(rates).copy()
    if 'valid_from' not in df_r.columns:
        return df_c
    df_r['valid_from'] = pd.to_datetime(df_r['valid_from'], utc=True)
    if 'valid_to' in df_r.columns:
        df_r['valid_to'] = pd.to_datetime(df_r['valid_to'], utc=True)
    else:
        df_r['valid_to'] = pd.NaT
    # sort
    df_r = df_r.sort_values('valid_from').reset_index(drop=True)
    starts = df_r['valid_from'].values
    # position of rightmost valid_from <= interval_start
    import numpy as np
    idx = np.searchsorted(starts, df_c['interval_start'].values, side='right') - 1
    df_c['rate_index'] = idx
    # mark invalid where idx < 0
    mask_valid = df_c['rate_index'] >= 0
    df_join = df_c[mask_valid].copy()
    df_join = df_join.merge(df_r.add_prefix('rate_'), left_on='rate_index', right_index=True, how='left')
    # filter by valid_to constraint
    cond = (df_join['interval_start'] >= df_join['rate_valid_from']) & (df_join['rate_valid_to'].isna() | (df_join['interval_start'] < df_join['rate_valid_to']))
    df_join = df_join[cond].copy()
    # choose unit rate inc VAT if present else ex VAT
    unit_col = 'rate_value_inc_vat' if 'rate_value_inc_vat' in df_join.columns else 'rate_value_ex_vat'
    df_join['unit_rate'] = df_join[unit_col]
    df_join['cost'] = df_join['consumption'] * df_join['unit_rate']
    return df_join.drop(columns=['rate_index'])

def detect_missing_intervals(consumption: List[Dict]) -> Tuple[int, int, int]:
    """Return (expected, actual, missing) for half-hour intervals in the span covered.
    If fewer than 2 records, missing = 0 (no baseline).
    """
    if len(consumption) < 2:
        return (len(consumption), len(consumption), 0)
    df = pd.DataFrame(consumption)
    if 'interval_end' not in df.columns:
        return (len(df), len(df), 0)
    df['interval_end'] = pd.to_datetime(df['interval_end'], utc=True)
    df = df.sort_values('interval_end')
    start = df['interval_end'].iloc[0] - pd.Timedelta(minutes=30)
    end = df['interval_end'].iloc[-1]
    span_minutes = (end - start).total_seconds() / 60
    expected = int(span_minutes / 30)
    actual = len(df)
    missing = max(0, expected - actual)
    return expected, actual, missing
