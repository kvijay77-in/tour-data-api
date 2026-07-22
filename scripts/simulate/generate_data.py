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
from datetime import date, datetime, timedelta, timezone
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
            'rider_id': f'R{i}',
            'profile_id': profile['profileId'],
            'status': 'REGISTERED',
            'qr_code_data': f'R{i}',
            'registered_at': '2026-01-15T00:00:00Z',
            'created_at': '2026-01-15T00:00:00Z',
            'updated_at': '2026-01-15T00:00:00Z',
        })

    return tour_riders


def _offset_time_hhmm(base_time, offset_minutes):
    """Return HH:MM offset from a base HH:MM time."""
    hour, minute = _parse_flag_off(base_time)
    total_minutes = max(0, hour * 60 + minute + offset_minutes)
    return f"{(total_minutes // 60) % 24:02d}:{total_minutes % 60:02d}"


def _offset_timestamp(base_date, base_time, offset_minutes):
    """Return ISO timestamp offset from a base date/time pair."""
    hour, minute = _parse_flag_off(base_time)
    base_dt = datetime.fromisoformat(
        f"{base_date}T{hour:02d}:{minute:02d}:00+00:00"
    )
    shifted = base_dt + timedelta(minutes=offset_minutes)
    return shifted.strftime('%Y-%m-%dT%H:%M:%SZ')


def _derive_close_time(flag_off_time, stages_cfg, fallback_minutes=720):
    """Derive ride close time from the latest planned pit-stop window."""
    latest_window_end = None
    for stage_def in stages_cfg:
        if stage_def.get('type') != 'PIT_STOP':
            continue
        estimated_open = int(stage_def.get('estimated_open_time', 0))
        duration = int(stage_def.get('pit_stop_duration', 0))
        latest_window_end = max(latest_window_end or 0, estimated_open + duration)

    return _offset_time_hhmm(flag_off_time, latest_window_end or fallback_minutes)


def _build_stages_for_ride(stage_templates, stage_count):
    """Build ordered stage definitions for a ride using start/pit/finish rules.

    Stage count includes start and finish. Pit stops are selected from
    templates in order and truncated to fit the requested count.
    """
    if stage_count < 2:
        raise ValueError("stage_count must be at least 2 (START and FINISH)")

    starts = [s for s in stage_templates if s.get('type') == 'START']
    finishes = [s for s in stage_templates if s.get('type') == 'FINISH']
    pit_stops = [s for s in stage_templates if s.get('type') == 'PIT_STOP']

    if not starts:
        raise ValueError("Stage templates must include a START stage")
    if not finishes:
        raise ValueError("Stage templates must include a FINISH stage")

    required_pit_stops = stage_count - 2
    if required_pit_stops > len(pit_stops):
        raise ValueError(
            f"Requested stage_count={stage_count} but only {len(pit_stops)} "
            "PIT_STOP definitions are available"
        )

    selected = [starts[0], *pit_stops[:required_pit_stops], finishes[-1]]
    return selected


def _apply_pit_stop_distances(stage_defs, pit_stop_distances):
    """Apply ride-level pit-stop distances to selected stage definitions.

    Supported formats for pit_stop_distances_from_start:
      - dict keyed by pit-stop stage name (e.g., PS1: 45)
      - dict keyed by pit-stop order 1..N (as int or string)
      - list in pit-stop order (index 0 -> first pit stop)
    """
    if pit_stop_distances is None:
        return stage_defs

    pit_stops = [s for s in stage_defs if s.get('type') == 'PIT_STOP']
    pit_stop_names = [s.get('name') for s in pit_stops]
    pit_stop_count = len(pit_stops)

    if isinstance(pit_stop_distances, list):
        if len(pit_stop_distances) > pit_stop_count:
            raise ValueError(
                "pit_stop_distances_from_start has more entries than "
                f"available PIT_STOP stages ({len(pit_stop_distances)} > {pit_stop_count})"
            )
    elif isinstance(pit_stop_distances, dict):
        for key in pit_stop_distances.keys():
            if key in pit_stop_names:
                continue

            key_str = str(key)
            if key_str.isdigit() and 1 <= int(key_str) <= pit_stop_count:
                continue

            raise ValueError(
                "Invalid pit_stop_distances_from_start key "
                f"'{key}'. Use pit-stop names {pit_stop_names} or "
                f"pit-stop order 1..{pit_stop_count}."
            )
    else:
        raise ValueError(
            "pit_stop_distances_from_start must be a list or dict"
        )

    updated = []
    pit_stop_idx = 0
    for stage_def in stage_defs:
        stage_copy = dict(stage_def)

        if stage_copy.get('type') == 'PIT_STOP':
            pit_stop_idx += 1
            distance = None

            if isinstance(pit_stop_distances, list):
                if pit_stop_idx <= len(pit_stop_distances):
                    distance = pit_stop_distances[pit_stop_idx - 1]
            else:
                stage_name = stage_copy.get('name')
                if stage_name in pit_stop_distances:
                    distance = pit_stop_distances[stage_name]
                elif pit_stop_idx in pit_stop_distances:
                    distance = pit_stop_distances[pit_stop_idx]
                elif str(pit_stop_idx) in pit_stop_distances:
                    distance = pit_stop_distances[str(pit_stop_idx)]

            if distance is not None:
                stage_copy['distance_from_start'] = distance

        updated.append(stage_copy)

    return updated


def _build_stage(stage_def, idx, base_date, flag_off_time, ride_status):
    """Build a simulated stage record with pit-stop planning/runtime fields."""
    stage = {
        'stage_id': f'S{idx:03d}',
        'stage_number': idx,
        'type': stage_def['type'],
        'name': stage_def['name'],
    }

    if stage_def.get('location') is not None:
        stage['location'] = stage_def['location']
    if stage_def.get('distance_from_start') is not None:
        stage['distance_from_start'] = Decimal(str(stage_def['distance_from_start']))

    if stage_def['type'] != 'PIT_STOP':
        return stage

    estimated_open_time = int(stage_def.get('estimated_open_time', idx * 90))
    pit_stop_duration = int(stage_def.get('pit_stop_duration', 45))
    stage['estimated_open_time'] = estimated_open_time
    stage['pit_stop_duration'] = pit_stop_duration

    if ride_status == 'STARTED':
        stage['pit_stop_status'] = 'OPEN'
        stage['opened_at'] = _offset_timestamp(base_date, flag_off_time, estimated_open_time)
    elif ride_status in ('COMPLETED', 'CLOSED'):
        stage['pit_stop_status'] = 'CLOSED'
        stage['opened_at'] = _offset_timestamp(base_date, flag_off_time, estimated_open_time)
        stage['closed_at'] = _offset_timestamp(
            base_date,
            flag_off_time,
            estimated_open_time + pit_stop_duration,
        )

    return stage


def _normalize_day_ride_configs(day_cfg):
    """Normalize day-level schedule config into per-ride definitions.

    Supported formats:
      - Legacy: day-level ride fields + rides_count
      - Refactored: explicit day.rides list with per-ride definitions
    """
    rides_cfg = day_cfg.get('rides')
    if rides_cfg is not None:
        if not isinstance(rides_cfg, list) or not rides_cfg:
            raise ValueError(
                f"Day {day_cfg.get('day', '?')}: 'rides' must be a non-empty list"
            )
        if 'rides_count' in day_cfg and int(day_cfg['rides_count']) != len(rides_cfg):
            raise ValueError(
                f"Day {day_cfg.get('day', '?')}: rides_count ({day_cfg['rides_count']}) "
                f"does not match rides list size ({len(rides_cfg)})"
            )
        return rides_cfg

    rides_count = int(day_cfg.get('rides_count', 1))
    if rides_count < 1:
        raise ValueError(
            f"Day {day_cfg.get('day', '?')}: rides_count must be at least 1"
        )
    return [{} for _ in range(rides_count)]


def build_rides(config):
    """
    Generate ride records from schedule configuration.

    Returns list of dicts with 'ride' (DynamoDB item) and 'day_config'
    (original YAML config for check-in generation).
    """
    rides_cfg = config['rides']
    default_stages_cfg = rides_cfg['default_stages']
    default_stage_count = int(rides_cfg.get('default_stage_count', 4))
    rides = []
    ride_counter = 1

    for day_cfg in config['rides']['schedule']:
        ride_defs = _normalize_day_ride_configs(day_cfg)
        rides_count = len(ride_defs)

        for ride_num, ride_cfg in enumerate(ride_defs, 1):
            ride_id = f"RIDE{ride_counter:03d}"
            status = ride_cfg.get('status', day_cfg.get('status', 'PLANNED'))
            flag_off = ride_cfg.get('flag_off_time', day_cfg.get('flag_off_time', '06:00'))

            # Build stages from day-level override or default, then apply
            # per-ride stage_count (includes START and FINISH).
            stage_templates = ride_cfg.get(
                'stages',
                day_cfg.get('stages', default_stages_cfg),
            )
            stage_count = int(
                ride_cfg.get(
                    'stage_count',
                    day_cfg.get('stage_count', default_stage_count),
                )
            )
            stages_cfg = _build_stages_for_ride(stage_templates, stage_count)
            stages_cfg = _apply_pit_stop_distances(
                stages_cfg,
                ride_cfg.get(
                    'pit_stop_distances_from_start',
                    day_cfg.get('pit_stop_distances_from_start'),
                ),
            )
            stages = []
            for idx, stage_def in enumerate(stages_cfg):
                stages.append(
                    _build_stage(stage_def, idx, day_cfg['date'], flag_off, status)
                )

            ride_name = ride_cfg.get('name', day_cfg.get('name', f"Day {day_cfg['day']}"))
            if rides_count > 1 and 'name' not in ride_cfg:
                ride_name = f"{ride_name} Ride {ride_num}"

            open_time = ride_cfg.get('open_time', day_cfg.get('open_time', flag_off))
            close_time = ride_cfg.get(
                'close_time',
                day_cfg.get('close_time', _derive_close_time(flag_off, stages_cfg)),
            )

            ride = {
                'ride_id': ride_id,
                'date': day_cfg['date'],
                'ride_no': ride_num,
                'name': ride_name,
                'start_location': ride_cfg.get(
                    'start_location', day_cfg.get('start_location', 'Start')
                ),
                'finish_location': ride_cfg.get(
                    'finish_location', day_cfg.get('finish_location', 'Finish')
                ),
                'total_distance': Decimal(
                    str(ride_cfg.get('distance', day_cfg.get('distance', 100)))
                ),
                'flag_off_time': flag_off,
                'open_time': open_time,
                'close_time': close_time,
                'status': status,
                'stages': stages,
                'created_at': '2026-02-01T00:00:00Z',
                'updated_at': '2026-02-01T00:00:00Z',
            }

            if status in ('COMPLETED', 'CLOSED'):
                ride['started_at'] = f"{day_cfg['date']}T{flag_off}:00Z"
                ride['completed_at'] = f"{day_cfg['date']}T18:00:00Z"
            elif status == 'STARTED':
                ride['started_at'] = f"{day_cfg['date']}T{flag_off}:00Z"

            checkin_cfg = ride_cfg.get('checkins', day_cfg.get('checkins'))
            rides.append(
                {
                    'ride': ride,
                    'day_config': day_cfg,
                    'ride_config': ride_cfg,
                    'checkin_cfg': checkin_cfg,
                }
            )
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
    if stage:
        stage_token = f"{stage['stage_number']:03d}"
        stage_number = stage['stage_number']
        stage_id = stage['stage_id']
    else:
        stage_token = '000'
        stage_number = None
        stage_id = None

    record = {
        'ride_id': ride_id,
        'check_in_id': f"{rider_id}#{stage_token}#{timestamp}",
        'rider_id': rider_id,
        'timestamp': timestamp,
        'checked_in_by': 'system',
        'method': 'QR_SCAN',
        'is_not_riding': False,
        'is_quit_riding': False,
        'is_manual_entry': False,
        'status': 'CHECKED_IN',
        'created_at': timestamp,
    }
    if stage_number is not None:
        record['stage_number'] = stage_number
    if stage_id is not None:
        record['stage_id'] = stage_id

    record.update(overrides)
    return record


def generate_checkins(rides_data, tour_riders, rng):
    """
    Generate check-in records based on per-ride check-in configurations.

    Processes each ride's checkins config to create NOT_RIDING, QUIT_RIDING,
    CHECKED_IN (finished), and in-progress check-in records.
    """

    all_checkins = []
    rider_ids = [r['rider_id'] for r in tour_riders]

    print(f"*** Check in created: {len(all_checkins)}")
    for ride_data in rides_data:
        ride = ride_data['ride']
        checkin_cfg = ride_data.get('checkin_cfg')

        if not checkin_cfg:
            continue

        print(f"----------------------------------------------------------------------")
        

        ride_id = ride['ride_id']
        stages = ride['stages']
        base_date = ride['date']
        flag_h, flag_m = _parse_flag_off(ride.get('flag_off_time', '06:00'))

        # Map stage names to indices
        stage_name_to_idx = {s['name']: idx for idx, s in enumerate(stages)}

        available = list(rider_ids)
        rng.shuffle(available)

        print(f" Available riders before check-in assignment for {ride_id}: {len(available)}")
        # --- Not Riding ---
        nr_count = checkin_cfg.get('not_riding', 0)
        nr_riders = available[:nr_count]
        available = available[nr_count:]

        for rid in nr_riders:
            ts = _make_timestamp(base_date, 0, rng, flag_h, flag_m)
            all_checkins.append(_checkin_record(
                ride_id, rid, None, ts,
                method='MANUAL',
                is_not_riding=True,
                is_manual_entry=True,
                status='NOT_RIDING',
            ))

        print(f" Available riders after NOT_RIDING assignment: {len(available)}")
        print(f"*** Check in created: {len(all_checkins)}")

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
                    ride_id, rid, None, quit_ts,
                    method='MANUAL',
                    is_quit_riding=True,
                    is_manual_entry=True,
                    status='QUIT_RIDING',
                ))
        
        print(f" Available riders after QUIT_RIDING assignment: {len(available)}")
        print(f"*** Check in created: {len(all_checkins)}")

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

        print(f" Available riders after FINISHED assignment: {len(available)}")
        print(f"*** Check in created: {len(all_checkins)}")

        temp_checkin_count_last = len(all_checkins)

        # --- In Progress (only for STARTED rides) ---
        in_progress_cfg = checkin_cfg.get('in_progress')
        if in_progress_cfg:
            for stage_name, count in in_progress_cfg.items():
                target_idx = stage_name_to_idx[stage_name]

                print(f"  Generating {count} in-progress riders for {ride_id} up to stage '{stage_name}'")
                print(f"    Available riders before assignment: {len(available)}")

                ip_riders = available[:count]
                available = available[count:]

                print(f"    Assigned {len(ip_riders)} in-progress riders, {len(available)} remaining unassigned")

                for rid in ip_riders:
                    # Checked in at all stages up to and including target
                    for s_idx in range(target_idx + 1):
                        ts = _make_timestamp(
                            base_date, s_idx, rng, flag_h, flag_m
                        )
                        all_checkins.append(_checkin_record(
                            ride_id, rid, stages[s_idx], ts,
                        ))
                temp_checkin_count = len(all_checkins)
                print(f"*** Check in created: {temp_checkin_count} (added {temp_checkin_count - temp_checkin_count_last})")
                temp_checkin_count_last = temp_checkin_count

        print(f" Available riders after IN_PROGRESS assignment for {ride_id}: {len(available)}")
        

        # Printing 10 random Check-in entries.
        print(f"====================================================================================")
        for sample_checkin in rng.sample(all_checkins, min(10, len(all_checkins))):
            print(f"  Sample Check-in: {sample_checkin}")
        print(f"====================================================================================")

        if available:
            print(f"  Warning: {len(available)} riders unassigned for {ride_id}")

    return all_checkins


def _stage_to_dynamodb(stage):
    """Convert snake_case stage attributes to DynamoDB table attribute names."""
    item = {
        'stageId': stage['stage_id'],
        'stageNumber': stage['stage_number'],
        'type': stage['type'],
        'name': stage['name'],
    }
    if stage.get('location') is not None:
        item['location'] = stage['location']
    if stage.get('distance_from_start') is not None:
        item['distanceFromStart'] = stage['distance_from_start']
    if stage.get('estimated_open_time') is not None:
        item['estimatedOpenTime'] = stage['estimated_open_time']
    if stage.get('pit_stop_duration') is not None:
        item['pitStopDuration'] = stage['pit_stop_duration']
    if stage.get('pit_stop_status') is not None:
        item['pitStopStatus'] = stage['pit_stop_status']
    if stage.get('opened_at') is not None:
        item['openedAt'] = stage['opened_at']
    if stage.get('closed_at') is not None:
        item['closedAt'] = stage['closed_at']
    return item


def _tour_rider_to_dynamodb(item):
    """Convert snake_case TourRider attributes to DynamoDB table attribute names."""
    return {
        'riderId': item['rider_id'],
        'profileId': item['profile_id'],
        'status': item['status'],
        'qrCodeData': item['qr_code_data'],
        'registeredAt': item['registered_at'],
        'createdAt': item['created_at'],
        'updatedAt': item['updated_at'],
    }


def _ride_to_dynamodb(item):
    """Convert snake_case Ride attributes to DynamoDB table attribute names."""
    ride = {
        'rideId': item['ride_id'],
        'date': item['date'],
        'rideNo': item['ride_no'],
        'name': item['name'],
        'startLocation': item['start_location'],
        'finishLocation': item['finish_location'],
        'totalDistance': item['total_distance'],
        'flagOffTime': item['flag_off_time'],
        'openTime': item['open_time'],
        'closeTime': item['close_time'],
        'status': item['status'],
        'stages': [_stage_to_dynamodb(s) for s in item['stages']],
        'createdAt': item['created_at'],
        'updatedAt': item['updated_at'],
    }
    if item.get('started_at'):
        ride['startedAt'] = item['started_at']
    if item.get('completed_at'):
        ride['completedAt'] = item['completed_at']
    if item.get('closed_at'):
        ride['closedAt'] = item['closed_at']
    return ride


def _checkin_to_dynamodb(item):
    """Convert snake_case CheckIn attributes to DynamoDB table attribute names."""
    checkin = {
        'rideId': item['ride_id'],
        'checkInId': item['check_in_id'],
        'riderId': item['rider_id'],
        'timestamp': item['timestamp'],
        'checkedInBy': item['checked_in_by'],
        'method': item['method'],
        'isNotRiding': item['is_not_riding'],
        'isQuitRiding': item['is_quit_riding'],
        'isManualEntry': item['is_manual_entry'],
        'status': item['status'],
        'createdAt': item['created_at'],
    }
    if item.get('stage_number') is not None:
        checkin['stageNumber'] = item['stage_number']
    if item.get('stage_id') is not None:
        checkin['stageId'] = item['stage_id']
    return checkin


def to_dynamodb_items(table_type, items):
    """Convert generated snake_case items to DynamoDB table attribute names."""
    if table_type == 'TourRider':
        return [_tour_rider_to_dynamodb(i) for i in items]
    if table_type == 'Ride':
        return [_ride_to_dynamodb(i) for i in items]
    if table_type == 'CheckIn':
        return [_checkin_to_dynamodb(i) for i in items]
    raise ValueError(f"Unsupported table type: {table_type}")


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

def resolve_schedule_dates(config, anchor_today=None):
    """
    Resolve missing schedule dates dynamically.

    Supported strategy:
    rides.date_strategy.mode = ride_number_anchor
      - anchor_ride_number: ride/day number to map to anchor date
      - anchor_date: "today" (default) or explicit YYYY-MM-DD
    """
    rides_cfg = config.get('rides', {})
    strategy = rides_cfg.get('date_strategy')
    schedule = rides_cfg.get('schedule', [])

    if not strategy:
        return

    mode = strategy.get('mode', 'ride_number_anchor')
    if mode != 'ride_number_anchor':
        raise ValueError(f"Unsupported date strategy mode: {mode}")

    anchor_ride = int(strategy.get('anchor_ride_number', 3))
    anchor_date_cfg = strategy.get('anchor_date', 'today')

    if anchor_today is None:
        anchor_today = date.today()

    if isinstance(anchor_date_cfg, str) and anchor_date_cfg.lower() == 'today':
        anchor_dt = anchor_today
    else:
        anchor_dt = date.fromisoformat(str(anchor_date_cfg))

    print("Resolving dynamic schedule dates...")
    print(
        f"  Strategy: ride_number_anchor "
        f"(ride {anchor_ride} -> {anchor_dt.isoformat()})"
    )

    for idx, day_cfg in enumerate(schedule, 1):
        ride_day_number = int(day_cfg.get('day', idx))
        resolved = anchor_dt + timedelta(days=ride_day_number - anchor_ride)
        day_cfg['date'] = resolved.isoformat()


def resolve_schedule_statuses(config):
    """
    Resolve schedule status from date strategy anchor ride.

    Rules:
      - day < anchor_ride_number: CLOSED
      - day == anchor_ride_number: STARTED
      - day > anchor_ride_number: PLANNED
    """
    rides_cfg = config.get('rides', {})
    strategy = rides_cfg.get('date_strategy') or {}
    schedule = rides_cfg.get('schedule', [])

    anchor_ride = int(strategy.get('anchor_ride_number', 3))

    print("Resolving schedule statuses from anchor ride...")
    print(f"  Status strategy: ride {anchor_ride} is STARTED")

    for idx, day_cfg in enumerate(schedule, 1):
        ride_day_number = int(day_cfg.get('day', idx))
        if ride_day_number < anchor_ride:
            day_cfg['status'] = 'CLOSED'
        elif ride_day_number == anchor_ride:
            day_cfg['status'] = 'STARTED'
        else:
            day_cfg['status'] = 'PLANNED'

        for ride_cfg in _normalize_day_ride_configs(day_cfg):
            ride_cfg['status'] = day_cfg['status']


def validate_schedule_dates(config):
    """Ensure all schedule entries have valid ISO dates before generation."""
    for idx, day_cfg in enumerate(config.get('rides', {}).get('schedule', []), 1):
        if 'date' not in day_cfg:
            raise ValueError(
                f"Missing date for schedule entry {idx}. "
                "Provide rides.date_strategy or explicit date values."
            )
        try:
            date.fromisoformat(str(day_cfg['date']))
        except ValueError as exc:
            raise ValueError(
                f"Invalid date '{day_cfg['date']}' in schedule entry {idx}. "
                "Expected YYYY-MM-DD."
            ) from exc


def validate_status_configuration(config):
    """Reject explicit schedule statuses when dynamic strategy is configured."""
    strategy = config.get('rides', {}).get('date_strategy')
    if not strategy:
        return

    bad_entries = []
    for idx, day_cfg in enumerate(config.get('rides', {}).get('schedule', []), 1):
        if 'status' in day_cfg:
            day = day_cfg.get('day', idx)
            bad_entries.append(str(day))
        for ride_idx, ride_cfg in enumerate(_normalize_day_ride_configs(day_cfg), 1):
            if 'status' in ride_cfg:
                day = day_cfg.get('day', idx)
                bad_entries.append(f"{day}.ride{ride_idx}")

    if bad_entries:
        raise ValueError(
            "Schedule 'status' must not be set when rides.date_strategy is "
            "configured. Remove status from day entries: "
            + ', '.join(bad_entries)
        )

def validate_scenario(config):
    """Validate the scenario configuration and print warnings for issues."""
    rider_count = config['tour_riders']['count']
    errors = []

    for day_idx, day_cfg in enumerate(config['rides']['schedule'], 1):
        day = day_cfg.get('day', day_idx)
        ride_defs = _normalize_day_ride_configs(day_cfg)

        for ride_idx, ride_cfg in enumerate(ride_defs, 1):
            checkin_cfg = ride_cfg.get('checkins', day_cfg.get('checkins'))
            if not checkin_cfg:
                continue

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
                    f"Day {day} ride {ride_idx}: assigned {assigned} riders "
                    f"but tour has {expected} (NR:{nr} + Quit:{quit_total} + "
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
        rc = [c for c in checkins if c['ride_id'] == ride['ride_id']]
        nr = len([c for c in rc if c.get('is_not_riding')])
        qr = len([c for c in rc if c.get('is_quit_riding')])
        normal = len(rc) - nr - qr
        print(
            f"    {ride['ride_id']} {ride['name']:<20s} "
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

    # Validate dynamic strategy usage before deriving values.
    validate_status_configuration(config)

    # Resolve dynamic schedule dates before any validation/build steps.
    resolve_schedule_dates(config)
    resolve_schedule_statuses(config)
    validate_schedule_dates(config)

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

        ddb_tour_riders = to_dynamodb_items('TourRider', tour_riders)
        ddb_rides = to_dynamodb_items('Ride', rides)
        ddb_checkins = to_dynamodb_items('CheckIn', checkins)

        table_name = f"{stack_name}-TourRider-{tour_id}"
        print(f"  Loading {len(tour_riders)} tour riders to {table_name}...")
        loaded, failed = load_to_dynamodb(dynamodb, table_name, ddb_tour_riders)
        print(f"    Loaded: {loaded}, Failed: {failed}")

        table_name = f"{stack_name}-Ride-{tour_id}"
        print(f"  Loading {len(rides)} rides to {table_name}...")
        loaded, failed = load_to_dynamodb(dynamodb, table_name, ddb_rides)
        print(f"    Loaded: {loaded}, Failed: {failed}")

        table_name = f"{stack_name}-CheckIn-{tour_id}"
        print(f"  Loading {len(checkins)} check-ins to {table_name}...")
        loaded, failed = load_to_dynamodb(dynamodb, table_name, ddb_checkins)
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
