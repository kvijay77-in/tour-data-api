# Test Data Simulation Utility

Generate and load tour-specific test data into DynamoDB tables for development and testing of the Tour Data API. This utility is template-driven — define a scenario in YAML and the script generates tour riders, rides, and check-in records accordingly.

**Important:** This script reads existing data from shared tables (RiderProfile, TourMaster) and only generates data for tour-specific tables (TourRider, Ride, CheckIn). Rider profiles and tour master records must already exist in DynamoDB.

## Prerequisites

- Python 3.11+
- AWS credentials configured (via AWS CLI, environment variables, or IAM role)
- Tour must already be provisioned — tour-specific tables must exist (use `scripts/provision_tour.py` or `POST /v1/tours` API)
- Rider profiles must exist in the shared RiderProfile table
- Dependencies: `boto3`, `pyyaml`

Install dependencies:

```bash
pip install -r scripts/simulate/requirements.txt
```

## Quick Start

```bash
# Dry run — generates JSON files, reads profiles/tour from DynamoDB
python scripts/simulate/generate_data.py \
    --scenario scripts/simulate/scenarios/tot_2026.yaml --dry-run

# Load test data to DynamoDB (cleans existing tour data first per config)
python scripts/simulate/generate_data.py \
    --scenario scripts/simulate/scenarios/tot_2026.yaml
```

## Usage

```
python scripts/simulate/generate_data.py --scenario <path> [options]
```

### Options

| Option | Description |
|---|---|
| `--scenario PATH` | **(Required)** Path to YAML scenario file |
| `--dry-run` | Output JSON files to `--output-dir` instead of writing to DynamoDB |
| `--clean` | Clean existing tour-specific table data before loading |
| `--clean-only` | Only clean data, do not generate or load new data |
| `--region REGION` | AWS region (overrides scenario config) |
| `--output-dir DIR` | Output directory for `--dry-run` (default: `scripts/simulate/output`) |

### Examples

```bash
# Generate and load to DynamoDB
python scripts/simulate/generate_data.py \
    --scenario scripts/simulate/scenarios/tot_2026.yaml

# Dry run to review data before loading
python scripts/simulate/generate_data.py \
    --scenario scripts/simulate/scenarios/tot_2026.yaml --dry-run

# Explicitly clean before loading (also controlled via options.clean_before_load in YAML)
python scripts/simulate/generate_data.py \
    --scenario scripts/simulate/scenarios/tot_2026.yaml --clean

# Only delete existing tour data
python scripts/simulate/generate_data.py \
    --scenario scripts/simulate/scenarios/tot_2026.yaml --clean-only

# Override AWS region
python scripts/simulate/generate_data.py \
    --scenario scripts/simulate/scenarios/tot_2026.yaml --region ap-south-1
```

## Scenario Configuration Reference

A scenario YAML file defines the tour-specific data to simulate. See `scenarios/tot_2026.yaml` for a full working example.

### Top-level Structure

```yaml
scenario:          # Metadata (name, description)
aws:               # AWS environment config (stack_name, region)
tour:              # Tour reference (tour_id, target_status)
tour_riders:       # Tour rider registration config
rides:             # Ride schedule and check-in distributions
options:           # Script behaviour flags
```

### `scenario`

```yaml
scenario:
  name: "Descriptive name"
  description: "What this scenario tests"
```

### `aws`

```yaml
aws:
  stack_name: dev           # CloudFormation stack name (table name prefix)
  region: ap-south-1        # Optional AWS region override
```

### `tour`

```yaml
tour:
  tour_id: TOT-2026                     # Must match an existing provisioned tour
  target_status: ACTIVE                  # Optional: update TourMaster status after load
```

### `tour_riders`

```yaml
tour_riders:
  count: 70                  # Number of riders picked from existing RiderProfile table
```

### `rides`

```yaml
rides:
  default_stages:            # Default stage layout (override per-day with 'stages' key)
    - { type: START, name: Start }
    - { type: PIT_STOP, name: PS1 }
    - { type: PIT_STOP, name: PS2 }
    - { type: FINISH, name: Finish }

  schedule:
    - day: 1
      date: "2026-02-10"
      name: "Day 1"
      start_location: "City A"
      finish_location: "City B"
      distance: 58               # km
      flag_off_time: "06:30"     # HH:MM
      rides_count: 1             # Number of rides this day (default: 1)
      status: COMPLETED          # PLANNED | ACTIVE | COMPLETED | CLOSED
      checkins: ...              # Check-in distribution (see below)
```

### Check-in Distribution

The `checkins` block defines how riders are distributed across different statuses for a ride.

```yaml
checkins:
  not_riding: 5                    # Riders marked as Not Riding at START

  quit:                            # Riders who quit at various stages
    - { after_stage: Start, count: 6 }   # Checked in at START, then quit
    - { after_stage: PS1, count: 6 }     # Checked in at START + PS1, then quit
    - { after_stage: PS2, count: 11 }    # Checked in at START + PS1 + PS2, then quit

  finished: all_remaining          # Or an explicit number (e.g., 42)
                                   # 'all_remaining' uses all riders not assigned above

  in_progress:                     # For ACTIVE rides only
    Start: 8                       # Riders whose latest check-in is at START
    PS1: 15                        # Riders checked in up to PS1
    PS2: 24                        # Riders checked in up to PS2
```

**Important:** Stage names in `after_stage` and `in_progress` keys must exactly match names from `default_stages` or the day's `stages` override.

**Rider assignment order:** not_riding → quit → finished → in_progress. The total across all categories must equal `tour_riders.count`.

### `options`

```yaml
options:
  clean_before_load: true    # Delete existing data from tour tables before loading
  update_tour_status: true   # Update TourMaster status to tour.target_status
  seed: 42                   # Random seed for reproducible data
```

## Data Generation Details

### What is READ from DynamoDB (not modified)

- **RiderProfile table** — fetches all existing profiles to use as the rider pool
- **TourMaster table** — validates the tour exists before generating data

### What is GENERATED and written

- **TourRider records** — randomly selected from existing profiles (seed-controlled), assigned sequential rider IDs: R1, R2, ... R{count}
- **Ride records** — sequential ride IDs: RIDE001, RIDE002, etc. Multi-ride days append "Ride N" to the name. Stages auto-numbered: S001, S002, S003, S004
- **CheckIn records** — realistic timestamps based on flag-off time and stage position:
  - Not Riding: single check-in at START with `isNotRiding=true`
  - Quit Riding: normal check-ins at completed stages + quit check-in (`isQuitRiding=true`) at the stage where they stopped
  - Finished: check-ins at all stages
  - In Progress: check-ins at stages up to and including the specified stage

### TourMaster status update

If `options.update_tour_status` is true and `tour.target_status` is set, the script updates the tour's status in TourMaster after loading data. This is the only write to a shared table.

## Creating Custom Scenarios

1. Copy `scenarios/tot_2026.yaml` to a new file
2. Modify tour ID, rider count, ride schedule, and check-in distributions
3. Ensure rider counts add up: `not_riding + quit + finished + in_progress = tour_riders.count`
4. Run with `--dry-run` first to verify the generated data
5. Run without `--dry-run` to load to DynamoDB

### Tips

- Change `seed` to get different random rider selections with the same config
- Use `finished: all_remaining` to auto-calculate finished riders
- PLANNED rides need no `checkins` block
- For multi-ride days, all rides on that day share the same check-in config (only applicable if rides have check-ins)

## File Structure

```
scripts/simulate/
├── README.md                   # This file
├── requirements.txt            # Python dependencies
├── generate_data.py            # Main data generation script
├── scenarios/                  # Scenario configuration files
│   └── tot_2026.yaml           # TOT-2026 tour scenario
└── output/                     # Dry-run JSON output (git-ignored)
```

## Limitations

- Multi-ride days with check-ins: when `rides_count > 1` and `checkins` is defined, the same check-in distribution is applied to each ride independently. For different distributions per ride on the same day, use separate day entries.
- The script does not create or provision DynamoDB tables. Tables must exist before running.
- Rider profiles must already exist in the RiderProfile table — the script does not create profiles.
