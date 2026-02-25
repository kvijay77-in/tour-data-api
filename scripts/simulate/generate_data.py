#!/usr/bin/env python3
"""
Test Data Generator for Tour Data API

Reads a YAML scenario configuration and generates tour-specific data
(TourRider, Ride, CheckIn) using existing rider profiles and tour master
data from DynamoDB.

Shared tables (RiderProfile, TourMaster) are READ-ONLY — the script fetches
existing profiles and validates the tour exists. Only tour-specific table
data is generated and written.

Usage:
    # Generate and load data to DynamoDB
    python scripts/simulate/generate_data.py \\
        --scenario scripts/simulate/scenarios/tot_2026.yaml

    # Dry run - output JSON files without writing to DynamoDB
    python scripts/simulate/generate_data.py \\
        --scenario scripts/simulate/scenarios/tot_2026.yaml --dry-run

    # Clean existing tour data before loading
    python scripts/simulate/generate_data.py \\
        --scenario scripts/simulate/scenarios/tot_2026.yaml --clean

    # Only clean, don't generate new data
    python scripts/simulate/generate_data.py \\
        --scenario scripts/simulate/scenarios/tot_2026.yaml --clean-only

Prerequisites:
    - Python 3.11+, boto3, pyyaml
    - AWS credentials configured
    - Tour must be provisioned (tables created via provision_tour.py or API)
    - Rider profiles must exist in RiderProfile table
"""

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone
from decimal import Decimal

import yaml
import boto3
from botocore.exceptions import ClientError


# ============================================================================
# DynamoDB READ — EXISTING DATA
# ============================================================================

def fetch_rider_profiles(dynamodb, stack_name):
    """
    Fetch all rider profiles from the shared RiderProfile table.

    Returns list of profile dicts.
    """
    table_name = f"{stack_name}-RiderProfile"
    table = dynamodb.Table(table_name)

    items = []
    response = table.scan()
    items.extend(response.get('Items', []))

    while 'LastEvaluatedKey' in response:
        response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        items.extend(response.get('Items', []))

    return items


def fetch_tour(dynamodb, stack_name, tour_id):
    """
    Fetch tour record from TourMaster table.

    Returns tour dict or None if not found.
    """
    table_name = f"{stack_name}-TourMaster"
    table = dynamodb.Table(table_name)

    response = table.get_item(Key={'tourId': tour_id})
    return response.get('Item')


# ============================================================================
# DATA GENERATION — TOUR-SPECIFIC ONLY
# ============================================================================

def select_tour_riders(profiles, count, rng):
    """
    Select riders from existing profile pool and assign tour-specific
    rider IDs (R1, R2, ... R{count}).
    """
    if count > len(profiles):
        print(
            f"  Error: requested {count} riders but only "
            f"{len(profiles)} profiles available"
        )
        sys.exit(1)

    selected = rng.sample(profiles, count)

    tour_riders = []
    for i, profile in enumerate(selected, 1):
        tour_riders.append({
            'riderId': f'R{i}',
            'profileId': profile['profileId'],
            'status': 'ACTIVE',
            'qrCodeData': f'R{i}',
            'registeredAt': '2026-01-15T00:00:00Z',
            'createdAt': '2026-01-15T00:00:00Z',
            'updatedAt': '2026-01-15T00:00:00Z',
        })

    return tour_riders


def build_rides(config):
    """
    Generate ride records from schedule configuration.

    Returns list of dicts with 'ride' (DynamoDB item) and 'day_config'
    (original YAML config for check-in generation).
    """
    default_stages_cfg = config['rides']['default_stages']
    rides = []
    ride_counter = 1

    for day_cfg in config['rides']['schedule']:
        rides_count = day_cfg.get('rides_count', 1)

        for ride_num in range(1, rides_count + 1):
            ride_id = f"RIDE{ride_counter:03d}"

            # Build stages from day-level override or default
            stages_cfg = day_cfg.get('stages', default_stages_cfg)
            stages = []
            for idx, stage_def in enumerate(stages_cfg, 1):
                stages.append({
                    'stageId': f'S{idx:03d}',
                    'stageNumber': idx,
                    'type': stage_def['type'],
                    'name': stage_def['name'],
                })

            ride_name = day_cfg.get('name', f"Day {day_cfg['day']}")
            if rides_count > 1:
                ride_name = f"{ride_name} Ride {ride_num}"

            status = day_cfg.get('status', 'PLANNED')
            flag_off = day_cfg.get('flag_off_time', '06:00')

            ride = {
                'rideId': ride_id,
                'date': day_cfg['date'],
                'rideNo': ride_num,
                'name': ride_name,
                'startLocation': day_cfg.get('start_location', 'Start'),
                'finishLocation': day_cfg.get('finish_location', 'Finish'),
                'totalDistance': Decimal(str(day_cfg.get('distance', 100))),
                'flagOffTime': flag_off,
                'status': status,
                'stages': stages,
                'createdAt': '2026-02-01T00:00:00Z',
                'updatedAt': '2026-02-01T00:00:00Z',
            }

            if status in ('COMPLETED', 'CLOSED'):
                ride['startedAt'] = f"{day_cfg['date']}T{flag_off}:00Z"
                ride['completedAt'] = f"{day_cfg['date']}T18:00:00Z"
            elif status == 'ACTIVE':
                ride['startedAt'] = f"{day_cfg['date']}T{flag_off}:00Z"

            rides.append({'ride': ride, 'day_config': day_cfg})
            ride_counter += 1

    return rides


def _parse_flag_off(flag_off_time):
    """Parse HH:MM flag-off time into (hour, minute)."""
    parts = flag_off_time.split(':')
    return int(parts[0]), int(parts[1])


def _make_timestamp(base_date, stage_index, rng, flag_h=6, flag_m=0):
    """
    Generate a realistic check-in timestamp for a given stage.

    Timestamps are offset from flag-off time based on stage position:
    - START:  -30 to 0 min (pre-start assembly)
    - PS1:    +60 to +120 min
    - PS2:    +150 to +240 min
    - FINISH: +270 to +420 min
    """
    offsets = {
        0: (-30, 0),
        1: (60, 120),
        2: (150, 240),
        3: (270, 420),
    }
    offset = offsets.get(stage_index, (60 * stage_index, 60 * stage_index + 60))

    total_min = flag_h * 60 + flag_m + rng.randint(offset[0], offset[1])
    hour = max(0, total_min) // 60
    minute = max(0, total_min) % 60
    second = rng.randint(0, 59)

    return f"{base_date}T{hour:02d}:{minute:02d}:{second:02d}Z"


def _make_quit_timestamp(base_date, stage_index, rng, flag_h=6, flag_m=0):
    """
    Generate a quit check-in timestamp slightly after the normal
    check-in window for the stage.
    """
    quit_offsets = {0: (15, 45), 1: (130, 160), 2: (250, 280), 3: (430, 460)}
    offset = quit_offsets.get(stage_index, (60 * stage_index + 30, 60 * stage_index + 60))

    total_min = flag_h * 60 + flag_m + rng.randint(offset[0], offset[1])
    hour = max(0, total_min) // 60
    minute = max(0, total_min) % 60
    second = rng.randint(0, 59)

    return f"{base_date}T{hour:02d}:{minute:02d}:{second:02d}Z"


def _checkin_record(ride_id, rider_id, stage, timestamp, **overrides):
    """Build a single check-in record dict."""
    record = {
        'rideId': ride_id,
        'checkInId': f"{rider_id}#{stage['stageNumber']:03d}#{timestamp}",
        'riderId': rider_id,
        'stageNumber': stage['stageNumber'],
        'stageId': stage['stageId'],
        'timestamp': timestamp,
        'checkedInBy': 'system',
        'method': 'QR_SCAN',
        'isNotRiding': False,
        'isQuitRiding': False,
        'isManualEntry': False,
        'status': 'CHECKED_IN',
        'createdAt': timestamp,
    }
    record.update(overrides)
    return record


def generate_checkins(rides_data, tour_riders, rng):
    """
    Generate check-in records based on per-ride check-in configurations.

    Processes each ride's checkins config to create NOT_RIDING, QUIT_RIDING,
    CHECKED_IN (finished), and in-progress check-in records.
    """
    all_checkins = []
    rider_ids = [r['riderId'] for r in tour_riders]

    for ride_data in rides_data:
        ride = ride_data['ride']
        day_cfg = ride_data['day_config']
        checkin_cfg = day_cfg.get('checkins')

        if not checkin_cfg:
            continue

        ride_id = ride['rideId']
        stages = ride['stages']
        base_date = day_cfg['date']
        flag_h, flag_m = _parse_flag_off(day_cfg.get('flag_off_time', '06:00'))

        # Map stage names to indices
        stage_name_to_idx = {s['name']: idx for idx, s in enumerate(stages)}

        available = list(rider_ids)
        rng.shuffle(available)

        # --- Not Riding ---
        nr_count = checkin_cfg.get('not_riding', 0)
        nr_riders = available[:nr_count]
        available = available[nr_count:]

        for rid in nr_riders:
            ts = _make_timestamp(base_date, 0, rng, flag_h, flag_m)
            all_checkins.append(_checkin_record(
                ride_id, rid, stages[0], ts,
                method='MANUAL',
                isNotRiding=True,
                isManualEntry=True,
                status='NOT_RIDING',
            ))

        # --- Quit Riding ---
        for quit_cfg in checkin_cfg.get('quit', []):
            stage_name = quit_cfg['after_stage']
            quit_count = quit_cfg['count']
            quit_stage_idx = stage_name_to_idx[stage_name]

            quit_riders = available[:quit_count]
            available = available[quit_count:]

            for rid in quit_riders:
                # Normal check-ins at all stages up to and including quit stage
                for s_idx in range(quit_stage_idx + 1):
                    ts = _make_timestamp(base_date, s_idx, rng, flag_h, flag_m)
                    all_checkins.append(_checkin_record(
                        ride_id, rid, stages[s_idx], ts,
                    ))

                # Quit check-in at the quit stage (later timestamp)
                quit_ts = _make_quit_timestamp(
                    base_date, quit_stage_idx, rng, flag_h, flag_m
                )
                all_checkins.append(_checkin_record(
                    ride_id, rid, stages[quit_stage_idx], quit_ts,
                    method='MANUAL',
                    isQuitRiding=True,
                    isManualEntry=True,
                    status='QUIT_RIDING',
                ))

        # --- Finished Riding ---
        finished_cfg = checkin_cfg.get('finished', 0)
        if finished_cfg == 'all_remaining':
            finished_count = len(available)
        else:
            finished_count = int(finished_cfg)

        finished_riders = available[:finished_count]
        available = available[finished_count:]

        for rid in finished_riders:
            for s_idx, stage in enumerate(stages):
                ts = _make_timestamp(base_date, s_idx, rng, flag_h, flag_m)
                all_checkins.append(_checkin_record(
                    ride_id, rid, stage, ts,
                ))

        # --- In Progress (only for ACTIVE rides) ---
        in_progress_cfg = checkin_cfg.get('in_progress')
        if in_progress_cfg:
            for stage_name, count in in_progress_cfg.items():
                target_idx = stage_name_to_idx[stage_name]

                ip_riders = available[:count]
                available = available[count:]

                for rid in ip_riders:
                    # Checked in at all stages up to and including target
                    for s_idx in range(target_idx + 1):
                        ts = _make_timestamp(
                            base_date, s_idx, rng, flag_h, flag_m
                        )
                        all_checkins.append(_checkin_record(
                            ride_id, rid, stages[s_idx], ts,
                        ))

        if available:
            print(f"  Warning: {len(available)} riders unassigned for {ride_id}")

    return all_checkins


# ============================================================================
# DynamoDB OPERATIONS — WRITE
# ============================================================================

def clean_table(table):
    """Delete all items from a DynamoDB table."""
    table.load()
    key_attrs = [k['AttributeName'] for k in table.key_schema]

    deleted = 0
    response = table.scan(ProjectionExpression=', '.join(key_attrs))

    with table.batch_writer() as batch:
        for item in response.get('Items', []):
            key = {k: item[k] for k in key_attrs}
            batch.delete_item(Key=key)
            deleted += 1

        while 'LastEvaluatedKey' in response:
            response = table.scan(
                ProjectionExpression=', '.join(key_attrs),
                ExclusiveStartKey=response['LastEvaluatedKey'],
            )
            for item in response.get('Items', []):
                key = {k: item[k] for k in key_attrs}
                batch.delete_item(Key=key)
                deleted += 1

    return deleted


def clean_tour_data(dynamodb, stack_name, tour_id):
    """Clean all data from tour-specific tables (not shared tables)."""
    table_types = ['TourRider', 'Ride', 'CheckIn']

    for table_type in table_types:
        table_name = f"{stack_name}-{table_type}-{tour_id}"
        try:
            table = dynamodb.Table(table_name)
            deleted = clean_table(table)
            print(f"  Cleaned {table_name}: {deleted} items deleted")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                print(f"  Skipped {table_name}: table not found")
            else:
                raise


def load_to_dynamodb(dynamodb, table_name, items):
    """Load items into a DynamoDB table using batch_writer."""
    table = dynamodb.Table(table_name)

    loaded = 0
    failed = 0
    with table.batch_writer() as batch:
        for item in items:
            try:
                batch.put_item(Item=item)
                loaded += 1
            except ClientError as e:
                failed += 1
                print(f"    Failed: {e.response['Error']['Message']}")

    return loaded, failed


def update_tour_status(dynamodb, stack_name, tour_id, status):
    """Update the tour status in TourMaster table."""
    table_name = f"{stack_name}-TourMaster"
    table = dynamodb.Table(table_name)

    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    table.update_item(
        Key={'tourId': tour_id},
        UpdateExpression='SET #status = :status, updatedAt = :now',
        ExpressionAttributeNames={'#status': 'status'},
        ExpressionAttributeValues={':status': status, ':now': now},
    )


# ============================================================================
# DRY RUN - JSON OUTPUT
# ============================================================================

def write_json(data, filepath):
    """Write data to a JSON file, converting Decimals to numbers."""
    def _default(obj):
        if isinstance(obj, Decimal):
            return float(obj) if obj != int(obj) else int(obj)
        raise TypeError(f"Not JSON serializable: {type(obj)}")

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2, default=_default)
    print(f"  Written: {filepath} ({len(data)} items)")


# ============================================================================
# VALIDATION
# ============================================================================

def validate_scenario(config):
    """Validate the scenario configuration and print warnings for issues."""
    rider_count = config['tour_riders']['count']
    errors = []

    for day_cfg in config['rides']['schedule']:
        checkin_cfg = day_cfg.get('checkins')
        if not checkin_cfg:
            continue

        day = day_cfg.get('day', '?')
        nr = checkin_cfg.get('not_riding', 0)
        quit_total = sum(q['count'] for q in checkin_cfg.get('quit', []))

        finished_cfg = checkin_cfg.get('finished', 0)
        if finished_cfg == 'all_remaining':
            finished = rider_count - nr - quit_total
        else:
            finished = int(finished_cfg)

        ip_total = sum(checkin_cfg.get('in_progress', {}).values())
        assigned = nr + quit_total + finished + ip_total
        expected = rider_count

        if finished_cfg != 'all_remaining' and assigned != expected:
            errors.append(
                f"Day {day}: assigned {assigned} riders but tour has "
                f"{expected} (NR:{nr} + Quit:{quit_total} + "
                f"Finished:{finished} + InProgress:{ip_total})"
            )

    if errors:
        print("\nScenario validation warnings:")
        for err in errors:
            print(f"  ⚠ {err}")
        print()

    return len(errors) == 0


# ============================================================================
# SUMMARY
# ============================================================================

def print_summary(tour_riders, rides_data, checkins):
    """Print a formatted summary of generated data."""
    print(f"\n{'─' * 60}")
    print("GENERATION SUMMARY")
    print(f"{'─' * 60}")
    print(f"  Tour riders    : {len(tour_riders)}")
    print(f"  Rides          : {len(rides_data)}")
    print(f"  Check-ins      : {len(checkins)}")

    print(f"\n  Per-ride breakdown:")
    for rd in rides_data:
        ride = rd['ride']
        rc = [c for c in checkins if c['rideId'] == ride['rideId']]
        nr = len([c for c in rc if c.get('isNotRiding')])
        qr = len([c for c in rc if c.get('isQuitRiding')])
        normal = len(rc) - nr - qr
        print(
            f"    {ride['rideId']} {ride['name']:<20s} "
            f"{ride['status']:<10s} "
            f"| records: {len(rc):>4d}  "
            f"(NR:{nr}, Quit:{qr}, Normal:{normal})"
        )

    print(f"{'─' * 60}\n")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Generate and load tour-specific test data for Tour Data API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Load test data to DynamoDB
  python scripts/simulate/generate_data.py \\
      --scenario scripts/simulate/scenarios/tot_2026.yaml

  # Dry run - output JSON files only
  python scripts/simulate/generate_data.py \\
      --scenario scripts/simulate/scenarios/tot_2026.yaml --dry-run

  # Clean existing data before loading
  python scripts/simulate/generate_data.py \\
      --scenario scripts/simulate/scenarios/tot_2026.yaml --clean

  # Only clean, don't generate
  python scripts/simulate/generate_data.py \\
      --scenario scripts/simulate/scenarios/tot_2026.yaml --clean-only

Note: RiderProfile and TourMaster data must already exist in DynamoDB.
      This script only generates tour-specific data (TourRider, Ride, CheckIn).
        """,
    )

    parser.add_argument(
        '--scenario', required=True,
        help='Path to scenario YAML file',
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Output JSON files instead of writing to DynamoDB',
    )
    parser.add_argument(
        '--clean', action='store_true',
        help='Clean existing tour-specific data before loading',
    )
    parser.add_argument(
        '--clean-only', action='store_true',
        help='Only clean data, do not generate or load',
    )
    parser.add_argument(
        '--region', default=None,
        help='AWS region (overrides scenario config)',
    )
    parser.add_argument(
        '--output-dir', default='scripts/simulate/output',
        help='Output directory for --dry-run JSON files (default: scripts/simulate/output)',
    )

    args = parser.parse_args()

    # Load scenario
    with open(args.scenario) as f:
        config = yaml.safe_load(f)

    scenario = config.get('scenario', {})
    aws_config = config.get('aws', {})
    tour_config = config['tour']
    options = config.get('options', {})

    stack_name = aws_config.get('stack_name', 'dev')
    tour_id = tour_config['tour_id']
    region = args.region or aws_config.get('region')
    seed = options.get('seed', 42)

    print(f"\n{'=' * 60}")
    print(f"  Scenario : {scenario.get('name', 'Unnamed')}")
    print(f"  Tour     : {tour_id}")
    print(f"  Stack    : {stack_name}")
    print(f"  Seed     : {seed}")
    print(f"  Mode     : {'DRY RUN' if args.dry_run else 'DynamoDB'}")
    print(f"{'=' * 60}\n")

    # Validate scenario
    validate_scenario(config)

    # Initialize DynamoDB — always needed to read existing data
    session_kwargs = {}
    if region:
        session_kwargs['region_name'] = region
    session = boto3.Session(**session_kwargs)
    dynamodb = session.resource('dynamodb')

    # Validate tour exists in TourMaster
    print("Fetching tour from TourMaster...")
    tour = fetch_tour(dynamodb, stack_name, tour_id)
    if not tour:
        print(f"  Error: Tour '{tour_id}' not found in {stack_name}-TourMaster")
        sys.exit(1)
    print(f"  Found: {tour.get('name')} (status: {tour.get('status')})")

    # Fetch existing rider profiles
    print("Fetching rider profiles from RiderProfile...")
    profiles = fetch_rider_profiles(dynamodb, stack_name)
    if not profiles:
        print(f"  Error: No profiles found in {stack_name}-RiderProfile")
        sys.exit(1)
    print(f"  Found {len(profiles)} profiles")

    rider_count = config['tour_riders']['count']
    if rider_count > len(profiles):
        print(
            f"  Error: scenario requests {rider_count} riders but only "
            f"{len(profiles)} profiles available"
        )
        sys.exit(1)

    # Clean if requested
    if (args.clean or args.clean_only or options.get('clean_before_load')) \
            and not args.dry_run:
        print("\nCleaning existing tour data...")
        clean_tour_data(dynamodb, stack_name, tour_id)

        if args.clean_only:
            print("\nClean complete.")
            return

    # Generate data
    rng = random.Random(seed)

    print("\nSelecting tour riders from existing profiles...")
    tour_riders = select_tour_riders(profiles, rider_count, rng)
    print(f"  Selected {len(tour_riders)} riders (R1-R{len(tour_riders)})")

    print("Building rides...")
    rides_data = build_rides(config)
    rides = [rd['ride'] for rd in rides_data]
    print(f"  Built {len(rides)} rides")

    print("Generating check-ins...")
    checkins = generate_checkins(rides_data, tour_riders, rng)
    print(f"  Generated {len(checkins)} check-in records")

    # Output
    if args.dry_run:
        print(f"\nWriting JSON files to {args.output_dir}/")
        write_json(tour_riders, os.path.join(args.output_dir, 'tour_riders.json'))
        write_json(rides, os.path.join(args.output_dir, 'rides.json'))
        write_json(checkins, os.path.join(args.output_dir, 'checkins.json'))
    else:
        print("\nLoading data to DynamoDB...")

        table_name = f"{stack_name}-TourRider-{tour_id}"
        print(f"  Loading {len(tour_riders)} tour riders to {table_name}...")
        loaded, failed = load_to_dynamodb(dynamodb, table_name, tour_riders)
        print(f"    Loaded: {loaded}, Failed: {failed}")

        table_name = f"{stack_name}-Ride-{tour_id}"
        print(f"  Loading {len(rides)} rides to {table_name}...")
        loaded, failed = load_to_dynamodb(dynamodb, table_name, rides)
        print(f"    Loaded: {loaded}, Failed: {failed}")

        table_name = f"{stack_name}-CheckIn-{tour_id}"
        print(f"  Loading {len(checkins)} check-ins to {table_name}...")
        loaded, failed = load_to_dynamodb(dynamodb, table_name, checkins)
        print(f"    Loaded: {loaded}, Failed: {failed}")

        # Update tour status
        if options.get('update_tour_status', True):
            target_status = tour_config.get('target_status')
            if target_status:
                print(f"\n  Updating tour status to {target_status}...")
                update_tour_status(dynamodb, stack_name, tour_id, target_status)
                print("    Done")

    print_summary(tour_riders, rides_data, checkins)
    print("Data generation complete!")


if __name__ == '__main__':
    main()
