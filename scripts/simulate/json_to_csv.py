import pandas as pd

# Load your JSON file (handles a list of JSON objects)
df = pd.read_json("scripts/simulate/output/checkins.json")

rider_seq_data = df["rider_id"].astype(str).str[1:]

# Find the location index of 'rider_id' & insert 'rider_seq' right after it.
target_idx = df.columns.get_loc("rider_id")
df.insert(loc=target_idx + 1, column="rider_seq", value=rider_seq_data)

# Export directly to a clean CSV
df.to_csv("scripts/simulate/output/checkins.csv", index=False)
