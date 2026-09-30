# Test Data Simulation Utility
_Last updated: 2026-09-29_

Generate and load tour-specific test data into DynamoDB tables for development and testing of the Tour Data API. This utility is template-driven — define a scenario in YAML and the script generates tour riders, rides, check-in records, or events-engine test data (event definitions, occurrences, activity scans, hotels, and room allocations) accordingly.

**Important:** Tour and event generation scenarios read existing data from shared tables (RiderProfile, TourMaster) and populate tour-specific tables. Rider profiles and the tour master record must already exist; event scenarios also require riders already registered for the tour by a `tour_data_generation` run. The separate `personal_code_update` scenario updates eligible rows in the shared `RiderProfile` table.

## Prerequisites

- Python 3.11+
- AWS credentials configured (via AWS CLI, environment variables, or IAM role)
- Tour must already be provisioned — tour-specific tables must exist (use `scripts/provision_tour.py` or `POST /v1/tours` API)
- Rider profiles must exist in the shared RiderProfile table
- Dependencies: `boto3`, `pandas`, and `PyYAML` (listed in `scripts/simulate/requirements.txt`)

Install dependencies:

```bash
source .venv/bin/activate
pip install -r scripts/simulate/requirements.txt
```

See the [Development Guide](../../docs/guides/development.md) for creating the project virtual environment.

## Quick Start

```bash
# Dry run — generates JSON files, reads profiles/tour from DynamoDB
python scripts/simulate/generate_data.py \
    --scenario scripts/simulate/scenarios/tot_2026.yaml --dry-run

# Load test data to DynamoDB (cleans existing tour data first per config)
python scripts/simulate/generate_data.py \
    --scenario scripts/simulate/scenarios/tot_2026.yaml

# Include today's ride check-ins (default skips today's check-ins)
python scripts/simulate/generate_data.py \
  --scenario scripts/simulate/scenarios/tot_2026.yaml --include-today-checkins

# Generate/load check-ins for today's ride only
python scripts/simulate/generate_data.py \
  --scenario scripts/simulate/scenarios/tot_2026.yaml --today-checkins-only

# Events engine: create a Day 0 Registration event + a fresh, PLANNED
# occurrence for today, ready for manual QR-scan testing from the start
python scripts/simulate/generate_data.py \
  --scenario scripts/simulate/scenarios/event_day0_registration.yaml

# Events engine: same, but seed today's occurrence with partial scans so
# manual testing can continue from mid-event
python scripts/simulate/generate_data.py \
  --scenario scripts/simulate/scenarios/event_day0_registration.yaml \
  --include-in-progress
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
| `--include-today-checkins` | Include today's ride check-ins (default behavior skips today's check-ins) |
| `--today-checkins-only` | Generate/load check-ins only for today's ride; skips TourRider and Ride writes |
| `--include-in-progress` | *(event_data_generation only)* Seed today's occurrence(s) with the partial activity records from the scenario's `in_progress` config, instead of leaving them freshly `PLANNED` with no scans |
| `--in-progress-only` | *(event_data_generation only)* Only (re)populate today's occurrence(s) and their in-progress activity records; skips event/hotel/room-allocation and historical-occurrence writes. Implies `--include-in-progress` |

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

# Include today's ride check-ins
python scripts/simulate/generate_data.py \
  --scenario scripts/simulate/scenarios/tot_2026.yaml --include-today-checkins

# Generate and load only today's ride check-ins
python scripts/simulate/generate_data.py \
  --scenario scripts/simulate/scenarios/tot_2026.yaml --today-checkins-only
```

### Today's Ride Check-In Behavior

- By default, today's ride check-ins are not generated.
- With dynamic status strategy, today's ride is set to `PLANNED` by default so pit-stop runtime fields remain empty (`pitStopStatus`, `openedAt`, `closedAt` are not set).
- Use `--include-today-checkins` when you want today's ride to be treated as started and have check-ins generated.
- Use `--today-checkins-only` to add only today's check-ins later (for example, after an initial run that skipped them).
- In `--today-checkins-only` mode, config-driven `clean_before_load` is ignored to avoid deleting previously loaded data.

## Scenario Configuration Reference

A scenario YAML file defines the tour-specific data to simulate. See `scenarios/tot_2026.yaml` for a full working example.

### Top-level Structure

```yaml
scenario:          # Metadata and scenario contract (type, mode, name, description)
aws:               # AWS environment config (stack_name, region)
tour:              # Tour reference (tour_id, target_status)
tour_riders:       # Tour rider registration config
rides:             # Ride schedule and check-in distributions
options:           # Script behaviour flags
```

### `scenario`

```yaml
scenario:
  type: "tour_data_generation"       # Required: scenario dispatcher key
  mode: "create"                     # Required: scenario execution mode
  name: "Descriptive name"
  description: "What this scenario tests"
```

Current supported scenario types:

- `tour_data_generation`: creates tour riders, rides, and check-ins for a provisioned tour
- `personal_code_update`: updates eligible RiderProfile rows with personal codes
- `event_data_generation`: creates events-engine test data (event definitions, occurrences, activity scans, hotels, and room allocations) for a provisioned tour — see [Event Engine Simulation Scenario](#event-engine-simulation-scenario)

Current supported scenario modes:

- `create`: used by generation scenarios
- `update`: used by shared-table update scenarios

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
  default_stage_count: 4      # Includes START + FINISH (default if omitted)
  default_stages:            # Default stage layout (override per-day with 'stages' key)
    - { type: START, name: Start }
    - { type: PIT_STOP, name: PS1 }
    - { type: PIT_STOP, name: PS2 }
    - { type: PIT_STOP, name: PS3 }
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
      stage_count: 4             # Optional per-ride override (START + 2 PIT_STOP + FINISH)
      pit_stop_distances_from_start:
        PS1: 22                  # Optional: distanceFromStart for PIT_STOP stages (km)
        PS2: 44
      status: COMPLETED          # PLANNED | ACTIVE | COMPLETED | CLOSED
      checkins: ...              # Check-in distribution (see below)

    # Multi-ride day with explicit per-ride configuration
    - day: 6
      date: "2026-02-15"
      name: "Day 6"
      rides:
        - name: "Day 6 Ride 1"
          start_location: "City A"
          finish_location: "City B"
          distance: 70
          flag_off_time: "07:30"
          pit_stop_distances_from_start: { PS1: 20, PS2: 45 }
          checkins: ...
        - name: "Day 6 Ride 2"
          start_location: "City C"
          finish_location: "City D"
          distance: 65
          flag_off_time: "12:30"
          pit_stop_distances_from_start: { PS1: 18, PS2: 40 }
          checkins: ...
```

  Stage selection rule: `stage_count` includes START and FINISH. PIT_STOP stages are taken in order from `default_stages` (or day-level `stages`) up to `stage_count - 2`.

  Multi-ride rule: for a day entry, choose one style:
- Legacy: `rides_count` with day-level ride fields
- Refactored: explicit `rides` list with per-ride fields

  When both day-level and per-ride fields exist, per-ride values override day-level values for that ride.

Pit-stop distance rule: `pit_stop_distances_from_start` is ride-level and applies only to `PIT_STOP` stages. It supports:
- Stage-name map: `PS1: 22, PS2: 44`
- Pit-stop order map: `1: 22, 2: 44`
- Ordered list: `[22, 44]`

These values are stored in stage `distanceFromStart` in DynamoDB ride records.

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

## Personal Code Update Scenario

The personal code use case now uses the same top-level `scenario` contract and a standard `target` / `selection` / `payload` structure.

```yaml
scenario:
  type: personal_code_update
  mode: update
  name: "Personal Code Loading"
  description: "Adds personal codes to eligible RiderProfile rows"

aws:
  stack_name: dev

target:
  table_name: RiderProfile
  attribute_name: personalCode

selection:
  filter:
    type: attribute_not_exists
    attribute: personalCode
  limit:
    type: reference_count
    source: personal_codes

payload:
  personal_codes:
    - D101
    - D102
  ignored_personal_codes:
    - D117
```

Field meanings:

- `target.table_name`: shared DynamoDB table to update
- `target.attribute_name`: attribute populated by this scenario
- `selection.filter`: reusable selection rule applied during the scan
- `selection.limit`: expected payload-driven selection size
- `payload`: scenario-specific input values used by the handler

## Event Engine Simulation Scenario

The `event_data_generation` scenario type populates the generic Events engine ([design](../../docs/design/events.md)) with test data for any event you define — there is no hardcoded event, activity, or occurrence content in `generate_data.py`; everything comes from the scenario YAML. Two ready-to-use scenarios are provided:

- `scenarios/event_day0_registration.yaml` — a single Day 0 Registration event
- `scenarios/event_baggage_handling.yaml` — linked Baggage Loading/Unloading events, plus hotels and room allocations

**This scenario reads riders from the tour-specific `TourRider-{tourId}` table** (populated by a prior `tour_data_generation` run, e.g. `tot_2026.yaml`) — it does not create riders itself. Run a tour-data scenario first.

### Top-level structure

```yaml
scenario:          # type: event_data_generation, mode: create
aws:               # AWS environment config (stack_name, region)
tour:              # Tour reference (tour_id) — must already be provisioned
date_strategy:     # anchor_date used as day_offset 0 ("today") for all occurrences/nights
riders:            # How to select existing TourRider records to use
hotels:            # Optional: Hotel-{tourId} master data
room_allocation:   # Optional: RoomAllocation-{tourId} generation rules
events:            # One or more full event definitions with activities and occurrences
options:           # Script behaviour flags (clean_before_load, seed)
```

### `riders`

```yaml
riders:
  source: tour_riders          # Only supported source: existing TourRider-{tourId} rows
  status_in: [REGISTERED, ACTIVE]   # Optional TourRider.status filter
  limit: 60                         # Optional cap on rider count (lowest rider IDs first)
```

### `hotels` and `room_allocation` (optional — for baggage-style events)

```yaml
hotels:
  - hotel_id: HTL-CHD-01
    name: Hotel Chidambaram Residency
    city: Chidambaram
    address: 1 Temple Street, Chidambaram
    contact: "+91-4144-123456"

room_allocation:
  room_capacity: 2                  # Riders per room (reciprocal sharingWith is generated automatically)
  room_number_start: 201
  nights:
    - day_offset: -1                # stayDate = anchor_date + day_offset
      hotel_id: HTL-CHD-01
    - day_offset: 0
      hotel_id: HTL-THJ-01
```

Riders are assigned round-robin into rooms of `room_capacity` for each configured night, one hotel per night, with `sharingWith` populated reciprocally on every room-mate's record.

### `events`

Each entry is a complete `Event-{tourId}` definition plus the occurrences to create for it:

```yaml
events:
  - event_id: EVT-REG
    event_name: "Day 0 Registration"
    event_type: SINGLE                        # SINGLE | REPEATING
    location: "Tour start venue"
    sequence_enforced: true
    default_allowed_type_codes: ["1"]
    activities:
      - activity_id: ACT-001
        name: "ID Card collection"
        sequence_no: 0
        mandatory: true                       # optional, default false
        allow_opt_out: false                  # optional, default false
        allowed_type_codes: []                 # optional, defaults to Event.default_allowed_type_codes
        prerequisite_activity_ids: []          # optional, default []
        restrict_to_assigned_users: true       # optional, default true
        variant_options: []                    # optional, e.g. [VEG, NON_VEG]

    occurrences:
      - day_offset: -2                         # date = anchor_date + day_offset
        seq: 1
        linked_event_id: null                  # for Baggage Loading <-> Unloading pairing
        progress:                              # only used when day_offset < 0 (historical)
          activity_outcomes:
            ACT-004:
              opted_out_ratio: 0.1              # fraction of riders recorded as OPTED_OUT
              variant_split: { VEG: 0.5, NON_VEG: 0.5 }
        in_progress:                           # only used for day_offset == 0 ("today")
          status: ACTIVE
          activity_distribution:                # riders whose furthest completed activity is the key
            ACT-003: 20
            ACT-002: 10
            ACT-001: 5
```

### Occurrence status and progress rules (generic, driven by `day_offset`)

| `day_offset` (relative to `date_strategy.anchor_date`) | Default behaviour | With `--include-in-progress` |
|---|---|---|
| `< 0` (past) | `COMPLETED`, fully populated per `progress` | same — unaffected by the flag |
| `== 0` ("today") | `PLANNED`, **zero** activity records — fresh start for manual QR-scan testing | occurrence status/records taken from `in_progress`; riders not listed in `activity_distribution` are left with no records so testing can start them from the first activity |
| `> 0` (future) | `PLANNED`, no records | no change — future occurrences are never seeded |

This directly supports the two testing modes requested for the events engine:

- **Start of event:** run the scenario with no extra flags — today's occurrence(s) are created `PLANNED` with no scans, ready for manual QR-scan testing from the very beginning.
- **Event already in progress:** run with `--include-in-progress` (or re-run later with `--in-progress-only` to avoid re-writing events/hotels/history) to pre-populate today's occurrence(s) per `in_progress.activity_distribution`, so manual testing can continue from that point for the riders not yet touched.

Linked occurrences (for example Baggage Loading/Unloading) are resolved automatically: an occurrence with `linked_event_id: EVT-X` is paired with the occurrence in event `EVT-X` that has the same `day_offset` and `seq`, and `linkedOccurrenceRef` is set on both sides.

## Data Generation Details

### What is READ from DynamoDB (not modified)

- **RiderProfile table** — fetches all existing profiles to use as the rider pool
- **TourMaster table** — validates the tour exists before generating data

### What is GENERATED and written

- **TourRider records** — randomly selected from existing profiles (seed-controlled), assigned sequential rider IDs: R1, R2, ... R{count}
- **Ride records** — sequential ride IDs: RIDE001, RIDE002, etc. Multi-ride days append "Ride N" to the name. Stages auto-numbered from S000 through the configured stage count for each ride.
- **CheckIn records** — realistic timestamps based on flag-off time and stage position:
  - Not Riding: single check-in at START with `isNotRiding=true`
  - Quit Riding: normal check-ins at completed stages + quit check-in (`isQuitRiding=true`) at the stage where they stopped
  - Finished: check-ins at all stages
  - In Progress: check-ins at stages up to and including the specified stage

### TourMaster status update

If `options.update_tour_status` is true and `tour.target_status` is set, the script updates the tour's status in TourMaster after loading data. This is the only write to a shared table.

## Creating Custom Scenarios

### Tour data (`tour_data_generation`)

1. Copy `scenarios/tot_2026.yaml` to a new file
2. Modify tour ID, rider count, ride schedule, and check-in distributions
3. Ensure rider counts add up: `not_riding + quit + finished + in_progress = tour_riders.count`
4. Run with `--dry-run` first to verify the generated data
5. Run without `--dry-run` to load to DynamoDB

### Events engine (`event_data_generation`)

1. Copy `scenarios/event_day0_registration.yaml` or `scenarios/event_baggage_handling.yaml` to a new file
2. Define your event(s)/activities/occurrences, and optional hotels/room allocations — no code changes are ever required
3. Run with `--dry-run` first to verify the generated events, occurrences, and activity records
4. Run without `--dry-run` to load to DynamoDB, adding `--include-in-progress` if you want today's occurrence(s) pre-seeded for continued manual testing

### Tips

- Change `seed` to get different random rider selections with the same config
- Use `finished: all_remaining` to auto-calculate finished riders
- PLANNED rides need no `checkins` block
- For multi-ride days, define `checkins` per ride using the `rides` list when distributions differ
- For events-engine scenarios, use `day_offset` (relative to `date_strategy.anchor_date`) rather than explicit dates, so re-running the scenario on a later date still produces a sensible "today"

## File Structure

```
scripts/simulate/
├── README.md                        # This file
├── generate_data.py                 # Main data generation script
├── scenarios/                       # Scenario configuration files
│   ├── tot_2026.yaml                # TOT-2026 tour scenario (tour_data_generation)
│   ├── event_day0_registration.yaml # Day 0 Registration event (event_data_generation)
│   └── event_baggage_handling.yaml  # Baggage Loading/Unloading events (event_data_generation)
└── output/                          # Dry-run JSON output (git-ignored)
```

## Limitations

- The script does not create or provision DynamoDB tables. Tables must exist before running.
- Rider profiles must already exist in the RiderProfile table — the script does not create profiles.
- `event_data_generation` scenarios require riders already registered in `TourRider-{tourId}` — run a `tour_data_generation` scenario for the tour first.
- `room_allocation` generation assigns a single hotel per configured night; multi-hotel nights require multiple manually-listed room allocation entries (not currently auto-generated).
