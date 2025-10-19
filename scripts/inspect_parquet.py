#!/usr/bin/env python3
"""Inspect a locally downloaded Octopus consumption parquet file.
Usage:
  python3 inspect_parquet.py /path/to/data.parquet
Outputs:
  - File size (bytes)
  - Row count
  - Schema
  - First 10 rows
  - Min/max of interval_start / interval_end columns if present
  - Distinct meter identifiers if present
"""
import sys
import os
import pandas as pd

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 inspect_parquet.py <parquet_file>")
        sys.exit(1)
    path = sys.argv[1]
    if not os.path.isfile(path):
        print(f"File not found: {path}")
        sys.exit(1)
    size = os.path.getsize(path)
    print(f"File: {path}")
    print(f"Size: {size} bytes")
    # Read with pandas (pyarrow engine by default if available)
    df = pd.read_parquet(path)
    print(f"Rows: {len(df)}")
    print("\nSchema:")
    for col, dtype in df.dtypes.items():
        print(f"  {col}: {dtype}")
    print("\nHead (10 rows):")
    print(df.head(10))
    for col in ["interval_start", "interval_end", "interval" ]:
        if col in df.columns:
            try:
                # Coerce to datetime
                s = pd.to_datetime(df[col], errors='coerce')
                print(f"\n{col}: min={s.min()} max={s.max()}")
            except Exception as e:
                print(f"Failed datetime parse for {col}: {e}")
    # Meter identifiers guess
    candidate_id_cols = [c for c in df.columns if any(k in c.lower() for k in ["mpan", "mprn", "serial", "meter"])]
    if candidate_id_cols:
        print("\nDistinct identifier counts:")
        for c in candidate_id_cols:
            print(f"  {c}: {df[c].nunique()} distinct")
    print("\nDone.")

if __name__ == "__main__":
    main()
