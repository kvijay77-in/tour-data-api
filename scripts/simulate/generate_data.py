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

    # Include today's ride check-ins (default skips them)
    python scripts/simulate/generate_data.py \\
        --scenario scripts/simulate/scenarios/tot_2026.yaml \\
        --include-today-checkins

    # Generate/load check-ins for today's ride only
    python scripts/simulate/generate_data.py \\
        --scenario scripts/simulate/scenarios/tot_2026.yaml \\
        --today-checkins-only

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
import re
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import yaml
import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Attr


SCENARIO_TYPE_TOUR_DATA = 'tour_data_generation'
SCENARIO_TYPE_PERSONAL_CODE = 'personal_code_update'
SCENARIO_TYPE_EVENT_DATA = 'event_data_generation'
SCENARIO_MODE_CREATE = 'create'
SCENARIO_MODE_UPDATE = 'update'
DEBUG_ENABLED = False

# ============================================================================
# SCENARIO AND DYNAMODB HELPERS
# ============================================================================

def require_mapping(container, key, context):
    """Return a required mapping from a parent container."""
    value = container.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{context}.{key} must be a mapping")
    return value


def require_list(container, key, context):
    """Return a required non-empty list from a parent container."""
    value = container.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{context}.{key} must be a non-empty list")
    return value


def validate_allowed_value(value, allowed_values, label):
    """Validate that a value is one of the supported options."""
    if value not in allowed_values:
        allowed = ', '.join(sorted(allowed_values))
        raise ValueError(f"{label} must be one of: {allowed}")


def get_scenario_metadata(config):
    """Return the normalized scenario metadata block."""
    scenario = config.get('scenario')
    if not isinstance(scenario, dict):
        raise ValueError('scenario must be a mapping')
    return scenario


def get_scenario_type(config):
    """Return the explicit scenario type."""
    scenario = get_scenario_metadata(config)
    scenario_type = scenario.get('type')
    validate_allowed_value(
        scenario_type,
        {SCENARIO_TYPE_PERSONAL_CODE, SCENARIO_TYPE_TOUR_DATA, SCENARIO_TYPE_EVENT_DATA},
        'scenario.type',
    )
    return scenario_type


def get_scenario_mode(config):
    """Return the explicit scenario mode."""
    scenario = get_scenario_metadata(config)
    mode = scenario.get('mode')
    validate_allowed_value(
        mode,
        {SCENARIO_MODE_CREATE, SCENARIO_MODE_UPDATE},
        'scenario.mode',
    )
    return mode


def build_table_name(stack_name, table_name, tour_id=None):
    """Build a shared or tour-specific DynamoDB table name."""
    if tour_id:
        return f"{stack_name}-{table_name}-{tour_id}"
    return f"{stack_name}-{table_name}"


def get_table(dynamodb, stack_name, table_name, tour_id=None):
    """Return a DynamoDB Table resource using project naming rules."""
    return dynamodb.Table(build_table_name(stack_name, table_name, tour_id=tour_id))


def scan_table_items(table, filter_expression=None, projection_expression=None, limit=None):
    """Scan all matching items from a DynamoDB table with optional filtering."""
    scan_kwargs = {}
    if filter_expression is not None:
        scan_kwargs['FilterExpression'] = filter_expression
    if projection_expression:
        scan_kwargs['ProjectionExpression'] = projection_expression

    items = []
    response = table.scan(**scan_kwargs)
    items.extend(response.get('Items', []))

    while 'LastEvaluatedKey' in response:
        response = table.scan(
            **scan_kwargs,
            ExclusiveStartKey=response['LastEvaluatedKey'],
        )
        items.extend(response.get('Items', []))

    if limit is not None:
        return items[:limit]
    return items


def fetch_table_items(
    dynamodb,
    stack_name,
    table_name,
    *,
    tour_id=None,
    filter_expression=None,
    projection_expression=None,
    limit=None,
):
    """Fetch items from a shared or tour-specific table."""

    print(f"Filtering {table_name} items with filter: {filter_expression}")
    table = get_table(dynamodb, stack_name, table_name, tour_id=tour_id)
    return scan_table_items(
        table,
        filter_expression=filter_expression,
        projection_expression=projection_expression,
        limit=limit,
    )


def fetch_table_item(dynamodb, stack_name, table_name, key, tour_id=None):
    """Fetch a single item from a shared or tour-specific table."""
    table = get_table(dynamodb, stack_name, table_name, tour_id=tour_id)
    response = table.get_item(Key=key)
    return response.get('Item')


def resolve_selection_filter(filter_config):
    """Convert a selection filter config into a DynamoDB condition."""
    if not filter_config:
        return None

    filter_type = filter_config.get('type')
    validate_allowed_value(
        filter_type,
        {'attribute_not_exists', 'attribute_exists'},
        'selection.filter.type',
    )

    if filter_type == 'attribute_not_exists':
        attribute_name = filter_config.get('attribute')
        if not attribute_name:
            raise ValueError(
                'selection.filter.attribute is required for attribute_not_exists'
            )
        return Attr(attribute_name).not_exists()

    if filter_type == 'attribute_exists':
        attribute_name = filter_config.get('attribute')
        if not attribute_name:
            raise ValueError(
                'selection.filter.attribute is required for attribute_exists'
            )
        return Attr(attribute_name).exists()

    raise ValueError(f"Unsupported selection filter type: {filter_type}")


def resolve_selection_limit(limit_config, config):
    """Resolve a selection limit from a scenario config."""
    if limit_config is None:
        return None

    if isinstance(limit_config, int):
        if limit_config < 1:
            raise ValueError('selection.limit must be at least 1')
        return limit_config

    if not isinstance(limit_config, dict):
        raise ValueError('selection.limit must be an integer or mapping')

    limit_type = limit_config.get('type')
    validate_allowed_value(limit_type, {'reference_count'}, 'selection.limit.type')

    source = limit_config.get('source')
    payload = config.get('payload', {})
    source_values = payload.get(source)
    if not isinstance(source_values, list):
        raise ValueError(
            'selection.limit.source must reference a list under payload'
        )
    return len(source_values)


def create_dynamodb_session(region=None):
    """Create a boto3 Session and DynamoDB resource."""
    session_kwargs = {}
    if region:
        session_kwargs['region_name'] = region
    session = boto3.Session(**session_kwargs)
    return session, session.resource('dynamodb')


def print_run_header(scenario_name, stack_name, seed, dry_run, extra_lines=None):
    """Print a consistent execution header for any scenario."""
    print(f"\n{'=' * 60}")
    print(f"  Scenario : {scenario_name}")
    print(f"  Stack    : {stack_name}")
    print(f"  Seed     : {seed}")
    print(f"  Mode     : {'DRY RUN' if dry_run else 'DynamoDB'}")
    for line in extra_lines or []:
        print(f"  {line}")
    print(f"{'=' * 60}\n")


# ============================================================================
# DynamoDB READ — EXISTING DATA
# ============================================================================

def fetch_rider_profiles(dynamodb, stack_name):
    """
    Fetch all rider profiles from the shared RiderProfile table.

    Returns list of profile dicts.
    """
    return fetch_table_items(dynamodb, stack_name, 'RiderProfile')


def fetch_tour(dynamodb, stack_name, tour_id):
    """
    Fetch tour record from TourMaster table.

    Returns tour dict or None if not found.
    """
    return fetch_table_item(
        dynamodb,
        stack_name,
        'TourMaster',
        {'tourId': tour_id},
    )


def fetch_tour_riders(dynamodb, stack_name, tour_id, status_in=None, limit=None):
    """
    Fetch existing rider IDs from the tour-specific TourRider table.

    Used by event-engine scenarios, which populate activity records against
    riders already registered by a prior tour-data scenario run rather than
    creating new riders themselves.
    """
    filter_expression = Attr('status').is_in(list(status_in)) if status_in else None
    items = fetch_table_items(
        dynamodb, stack_name, 'TourRider', tour_id=tour_id,
        filter_expression=filter_expression,
    )
    rider_ids = sorted(
        (item['riderId'] for item in items),
        key=lambda rider_id: int(re.sub(r'\D', '', rider_id) or 0),
    )
    if limit is not None:
        rider_ids = rider_ids[:limit]
    return rider_ids


def validate_scenario_contract(config):
    """Validate the common scenario header shared by all scenario types."""
    scenario = get_scenario_metadata(config)
    if not scenario.get('name'):
        raise ValueError('scenario.name is required')
    if not scenario.get('description'):
        raise ValueError('scenario.description is required')

    scenario_type = get_scenario_type(config)
    mode = get_scenario_mode(config)
    expected_mode = {
        SCENARIO_TYPE_PERSONAL_CODE: SCENARIO_MODE_UPDATE,
        SCENARIO_TYPE_TOUR_DATA: SCENARIO_MODE_CREATE,
        SCENARIO_TYPE_EVENT_DATA: SCENARIO_MODE_CREATE,
    }[scenario_type]
    if mode != expected_mode:
        raise ValueError(
            f"scenario.mode must be '{expected_mode}' for scenario.type '{scenario_type}'"
        )


def validate_personal_code_scenario(config):
    """Validate the personal-code loading scenario structure."""
    validate_scenario_contract(config)

    errors = []
    target = require_mapping(config, 'target', 'config')
    payload = require_mapping(config, 'payload', 'config')
    selection = require_mapping(config, 'selection', 'config')
    filter_config = require_mapping(selection, 'filter', 'selection')

    if get_scenario_type(config) != SCENARIO_TYPE_PERSONAL_CODE:
        errors.append(
            f"scenario.type must be '{SCENARIO_TYPE_PERSONAL_CODE}'"
        )
    if target.get('table_name') != 'RiderProfile':
        errors.append("target.table_name must be 'RiderProfile'")
    if target.get('attribute_name') != 'personalCode':
        errors.append("target.attribute_name must be 'personalCode'")

    if filter_config.get('type') != 'attribute_not_exists':
        errors.append(
            "selection.filter.type must be 'attribute_not_exists'"
        )
    if filter_config.get('attribute') != 'personalCode':
        errors.append("selection.filter.attribute must be 'personalCode'")

    personal_codes = payload.get('personal_codes')
    if not isinstance(personal_codes, list) or not personal_codes:
        errors.append('payload.personal_codes must be a non-empty list')

    limit_config = selection.get('limit')
    if limit_config is not None:
        try:
            resolve_selection_limit(limit_config, config)
        except ValueError as exc:
            errors.append(str(exc))

    try:
        resolve_selection_filter(filter_config)
    except ValueError as exc:
        errors.append(str(exc))

    if errors:
        raise ValueError('Invalid personal code scenario: ' + '; '.join(errors))


def validate_tour_data_scenario(config):
    """Validate the common contract for the tour data generation scenario."""
    validate_scenario_contract(config)
    if get_scenario_type(config) != SCENARIO_TYPE_TOUR_DATA:
        raise ValueError(
            f"scenario.type must be '{SCENARIO_TYPE_TOUR_DATA}'"
        )
    if 'tour' not in config or 'tour_riders' not in config or 'rides' not in config:
        raise ValueError(
            'Tour data scenario requires tour, tour_riders, and rides sections'
        )


def validate_event_data_scenario(config):
    """Validate the generic event-engine simulation scenario structure.

    This only validates shape/structure — event, activity, and occurrence
    *content* is entirely scenario-config driven and is never hardcoded here.
    """
    validate_scenario_contract(config)
    if get_scenario_type(config) != SCENARIO_TYPE_EVENT_DATA:
        raise ValueError(
            f"scenario.type must be '{SCENARIO_TYPE_EVENT_DATA}'"
        )

    tour_cfg = require_mapping(config, 'tour', 'config')
    if not tour_cfg.get('tour_id'):
        raise ValueError('tour.tour_id is required')

    events_cfg = require_list(config, 'events', 'config')
    event_ids = set()
    for event_index, event_cfg in enumerate(events_cfg, 1):
        context = f"events[{event_index}]"
        if not isinstance(event_cfg, dict):
            raise ValueError(f"{context} must be a mapping")

        event_id = event_cfg.get('event_id')
        if not event_id:
            raise ValueError(f"{context}.event_id is required")
        if event_id in event_ids:
            raise ValueError(f"Duplicate event_id '{event_id}' in events")
        event_ids.add(event_id)

        for required_field in ('event_name', 'event_type', 'location', 'sequence_enforced',
                                'default_allowed_type_codes'):
            if required_field not in event_cfg:
                raise ValueError(f"{context}.{required_field} is required")

        activities_cfg = require_list(event_cfg, 'activities', context)
        for activity_index, activity_cfg in enumerate(activities_cfg, 1):
            if not isinstance(activity_cfg, dict):
                raise ValueError(f"{context}.activities[{activity_index}] must be a mapping")
            for required_field in ('activity_id', 'name', 'sequence_no'):
                if required_field not in activity_cfg:
                    raise ValueError(
                        f"{context}.activities[{activity_index}].{required_field} is required"
                    )

        occurrences_cfg = require_list(event_cfg, 'occurrences', context)
        for occ_index, occurrence_cfg in enumerate(occurrences_cfg, 1):
            if not isinstance(occurrence_cfg, dict):
                raise ValueError(f"{context}.occurrences[{occ_index}] must be a mapping")
            for required_field in ('day_offset', 'seq'):
                if required_field not in occurrence_cfg:
                    raise ValueError(
                        f"{context}.occurrences[{occ_index}].{required_field} is required"
                    )

    for hotel_index, hotel_cfg in enumerate(config.get('hotels') or [], 1):
        if not hotel_cfg.get('hotel_id'):
            raise ValueError(f"hotels[{hotel_index}].hotel_id is required")

    room_allocation_cfg = config.get('room_allocation')
    if room_allocation_cfg is not None:
        require_list(room_allocation_cfg, 'nights', 'room_allocation')


def _normalize_personal_codes(config):
    """Return the usable personal codes after removing ignored entries."""
    ignored = {
        str(code).strip().upper()
        for code in config.get('payload', {}).get('ignored_personal_codes', [])
        if str(code).strip()
    }

    usable = []
    for code in config.get('payload', {}).get('personal_codes', []):
        normalized = str(code).strip().upper()
        if not normalized or normalized in ignored:
            continue
        usable.append(normalized)

    seen = set()
    duplicates = []
    for code in usable:
        if code in seen:
            duplicates.append(code)
        seen.add(code)

    if duplicates:
        raise ValueError(
            'personal_codes contains duplicate values after normalization: '
            + ', '.join(sorted(set(duplicates)))
        )

    return usable, sorted(ignored)


def fetch_eligible_rider_profiles(dynamodb, stack_name, config, select_path=None):
    """Fetch rider profiles as per the filter defined in the scenario selection section."""

    target = 'RiderProfile'
    if select_path is None:
        selection = config['selection']
    else:
        selection = config[select_path]['selection']

    print(f"Validating selection filter for selection...")

    print('Fetching rider profiles from RiderProfile...')
    eligible_profiles = fetch_table_items(
        dynamodb,
        stack_name,
        target,
        filter_expression=resolve_selection_filter(selection.get('filter')),
    )

    print(f'  Found {len(eligible_profiles)} ')
    return eligible_profiles


def assign_personal_codes(dynamodb, stack_name, config, rng, dry_run=False):
    """Randomly assign personal codes to eligible RiderProfile items."""
    validate_personal_code_scenario(config)

    target = config['target']
    selection = config['selection']
    attribute_name = target['attribute_name']
    usable_codes, ignored_codes = _normalize_personal_codes(config)
    expected_selection_size = resolve_selection_limit(selection.get('limit'), config)

    print('Fetching rider profiles from RiderProfile...')
    eligible_profiles = fetch_table_items(
        dynamodb,
        stack_name,
        target['table_name'],
        filter_expression=resolve_selection_filter(selection.get('filter')),
    )
    print(f'  Found {len(eligible_profiles)} eligible profiles without {attribute_name}')

    if expected_selection_size is not None and expected_selection_size != len(usable_codes):
        raise ValueError(
            'selection.limit resolved to a different size than the usable payload set'
        )

    if len(usable_codes) > len(eligible_profiles):
        raise ValueError(
            f"Scenario needs {len(usable_codes)} eligible riders but only "
            f"{len(eligible_profiles)} profiles are available without {attribute_name}"
        )

    selected_profiles = rng.sample(eligible_profiles, len(usable_codes))
    assignments = [
        {
            'profileId': profile['profileId'],
            'name': profile.get('name'),
            attribute_name: code,
        }
        for profile, code in zip(selected_profiles, usable_codes)
    ]

    print(f"  Loaded {len(usable_codes)} personal codes")
    if ignored_codes:
        print(f"  Ignored {len(ignored_codes)} pre-loaded code(s)")

    if dry_run:
        return assignments

    table = get_table(dynamodb, stack_name, target['table_name'])
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    loaded = 0
    failed = 0
    for assignment in assignments:
        try:
            table.update_item(
                Key={'profileId': assignment['profileId']},
                UpdateExpression='SET personalCode = :code, updatedAt = :now',
                ConditionExpression=Attr('personalCode').not_exists(),
                ExpressionAttributeValues={
                    ':code': assignment['personalCode'],
                    ':now': now,
                },
            )
            loaded += 1
        except ClientError as e:
            failed += 1
            print(
                f"  Failed to update {assignment['profileId']} "
                f"({assignment.get('name')}): {e.response['Error']['Message']}"
            )

    print(f"  Updated {loaded} rider profile(s), Failed: {failed}")

    if failed:
        raise RuntimeError('One or more RiderProfile updates failed')

    return assignments


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
        if DEBUG_ENABLED:
            print(f"  Selected {profile['profileId']} ({profile.get('personalCode')}) as R{i}")
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
    if 'self_check_in_allowed' in stage_def:
        stage['self_check_in_allowed'] = stage_def['self_check_in_allowed']
    if 'self_not_riding_allowed' in stage_def:
        stage['self_not_riding_allowed'] = stage_def['self_not_riding_allowed']

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

            # Normalize and attach floats if defined at ride or day level.
            floats_cfg = ride_cfg.get('floats', day_cfg.get('floats'))
            if floats_cfg is not None:
                normalized_floats = []
                total_stages = len(stages_cfg)
                for f_idx, f in enumerate(floats_cfg):
                    if not isinstance(f, dict):
                        raise ValueError(
                            f"Day {day_cfg.get('day','?')}: floats[{f_idx}] must be a mapping"
                        )

                    # Accept multiple possible key namings from scenario files
                    if 'floatNo' in f:
                        float_no = f['floatNo']
                    elif 'float_no' in f:
                        float_no = f['float_no']
                    elif 'float' in f:
                        float_no = f['float']
                    else:
                        raise ValueError(
                            f"Day {day_cfg.get('day','?')}: floats[{f_idx}] missing float number key"
                        )

                    if 'floatToStage' in f:
                        float_to_stage = f['floatToStage']
                    elif 'float_to_stage' in f:
                        float_to_stage = f['float_to_stage']
                    elif 'float_to' in f:
                        float_to_stage = f['float_to']
                    elif 'floatTo' in f:
                        float_to_stage = f['floatTo']
                    else:
                        raise ValueError(
                            f"Day {day_cfg.get('day','?')}: floats[{f_idx}] missing float-to-stage key"
                        )

                    try:
                        float_no = int(float_no)
                        float_to_stage = int(float_to_stage)
                    except Exception:
                        raise ValueError(
                            f"Day {day_cfg.get('day','?')}: floats[{f_idx}] float values must be integers"
                        )

                    # Validate target stage is within allowed range (1..total_stages-1)
                    if total_stages < 2 or float_to_stage < 1 or float_to_stage >= total_stages:
                        raise ValueError(
                            f"Day {day_cfg.get('day','?')}: floats[{f_idx}] float_to_stage {float_to_stage} out of range for {total_stages} stages"
                        )

                    normalized_floats.append({
                        'float_no': float_no,
                        'float_to_stage': float_to_stage,
                    })
            else:
                normalized_floats = None

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
                # Attach floats only when defined in config
                **({'floats': normalized_floats} if normalized_floats is not None else {}),
                'created_at': '2026-02-01T00:00:00Z',
                'updated_at': '2026-02-01T00:00:00Z',
            }
            for setting in ('self_check_in_allowed', 'self_quit_riding_allowed'):
                value = ride_cfg.get(setting, day_cfg.get(setting, rides_cfg.get(setting)))
                if value is not None:
                    ride[setting] = value

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


def apply_rider_exits(rides_data, tour_riders, rng):
    """
    Apply `rider_exit` directives from ride/day configs.

    For each ride in `rides_data`, if the ride or its day config has a
    `rider_exit` value > 0, select that many currently-REGISTERED riders
    from `tour_riders`, mark them with status 'EXITED' and set
    `exited_at` to the ride's start timestamp (date + flag_off_time).

    Modifies `tour_riders` in-place and returns a list of exited rider_ids.
    """
    exited = []

    for rd in rides_data:
        ride = rd.get('ride', {})
        day_cfg = rd.get('day_config', {})
        ride_cfg = rd.get('ride_config', {}) or {}

        # rider_exit may be specified at ride or day level
        raw_exit = ride_cfg.get('rider_exit', day_cfg.get('rider_exit'))
        if raw_exit is None:
            continue

        try:
            exit_count = int(raw_exit)
        except Exception:
            print(f"  Warning: invalid rider_exit value '{raw_exit}' for {ride.get('ride_id')}")
            continue

        if exit_count <= 0:
            continue

        # Select from currently registered riders only
        registered = [r for r in tour_riders if r.get('status') == 'REGISTERED']
        if not registered:
            print(f"  Warning: no REGISTERED riders available to exit for {ride.get('ride_id')}")
            continue

        if exit_count > len(registered):
            print(
                f"  Warning: rider_exit {exit_count} > available REGISTERED riders {len(registered)}; reducing"
            )
            exit_count = len(registered)

        rng.shuffle(registered)
        to_exit = registered[:exit_count]

        # Use ride start timestamp (YYYY-MM-DDTHH:MM:00Z)
        start_ts = ride.get('started_at') or f"{ride.get('date')}T{ride.get('flag_off_time')}:00Z"

        for r in to_exit:
            r['status'] = 'EXITED'
            r['exited_at'] = start_ts
            exited.append(r['rider_id'])

        print(f"  Marked {len(to_exit)} rider(s) as EXITED at {start_ts} for {ride.get('ride_id')}")

    return exited


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


def generate_checkins(
    rides_data,
    tour_riders,
    rng,
    include_today_checkins=False,
    today_checkins_only=False,
    today_iso_date=None,
):
    """
    Generate check-in records based on per-ride check-in configurations.

    Processes each ride's checkins config to create NOT_RIDING, QUIT_RIDING,
    CHECKED_IN (finished), and in-progress check-in records.
    """

    all_checkins = []
    skipped_today_rides = 0
    skipped_non_today_rides = 0

    # Helper to check if a rider is active for a given ride.
    def _rider_active_for_ride(rider, ride):
        # Non-exited riders are active
        if rider.get('status') != 'EXITED':
            return True
        exited_ts = rider.get('exited_at')
        if not exited_ts:
            return False
        # Ride start timestamp (use started_at if present, otherwise derive)
        ride_start = ride.get('started_at') or f"{ride.get('date')}T{ride.get('flag_off_time')}:00Z"
        # Exclude rider if they exited at or before ride start
        return exited_ts > ride_start

    if today_iso_date is None:
        today_iso_date = date.today().isoformat()

    if DEBUG_ENABLED:
        print(f"*** Check in created: {len(all_checkins)}")

    for ride_data in rides_data:
        ride = ride_data['ride']
        checkin_cfg = ride_data.get('checkin_cfg')
        is_today_ride = ride.get('date') == today_iso_date

        if today_checkins_only and not is_today_ride:
            skipped_non_today_rides += 1
            continue

        if not include_today_checkins and is_today_ride:
            skipped_today_rides += 1
            continue

        if not checkin_cfg:
            continue

        if DEBUG_ENABLED:
            print(f"----------------------------------------------------------------------")
        

        ride_id = ride['ride_id']
        stages = ride['stages']
        base_date = ride['date']
        flag_h, flag_m = _parse_flag_off(ride.get('flag_off_time', '06:00'))

        # Map stage names to indices
        stage_name_to_idx = {s['name']: idx for idx, s in enumerate(stages)}

        # Build per-ride available rider list excluding those who exited
        active_rider_ids = [r['rider_id'] for r in tour_riders if _rider_active_for_ride(r, ride)]
        available = list(active_rider_ids)
        rng.shuffle(available)

        if DEBUG_ENABLED:
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

        if DEBUG_ENABLED:
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
        
        if DEBUG_ENABLED:
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

        if DEBUG_ENABLED:
            print(f" Available riders after FINISHED assignment: {len(available)}")
            print(f"*** Check in created: {len(all_checkins)}")

        temp_checkin_count_last = len(all_checkins)

        # --- In Progress (only for STARTED rides) ---
        in_progress_cfg = checkin_cfg.get('in_progress')
        if in_progress_cfg:
            for stage_name, count in in_progress_cfg.items():
                target_idx = stage_name_to_idx[stage_name]

                if DEBUG_ENABLED:
                    print(f"  Generating {count} in-progress riders for {ride_id} up to stage '{stage_name}'")
                    print(f"    Available riders before assignment: {len(available)}")

                ip_riders = available[:count]
                available = available[count:]

                if DEBUG_ENABLED:
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
                if DEBUG_ENABLED:
                    print(f"*** Check in created: {temp_checkin_count} (added {temp_checkin_count - temp_checkin_count_last})")
                temp_checkin_count_last = temp_checkin_count

        if DEBUG_ENABLED:
            print(f" Available riders after IN_PROGRESS assignment for {ride_id}: {len(available)}")
        
        # Printing 10 random Check-in entries.
        if DEBUG_ENABLED:
            print(f"====================================================================================")
            for sample_checkin in rng.sample(all_checkins, min(10, len(all_checkins))):
                print(f"  Sample Check-in: {sample_checkin}")
            print(f"====================================================================================")

        if available:
            print(f"  Warning: {len(available)} riders unassigned for {ride_id}")

    if skipped_today_rides:
        print(
            f"Skipped check-in generation for {skipped_today_rides} "
            f"today ride(s) on {today_iso_date} "
            f"(use --include-today-checkins to include)."
        )

    if today_checkins_only and skipped_non_today_rides:
        print(
            f"Generated check-ins only for rides on {today_iso_date}; "
            f"skipped {skipped_non_today_rides} non-today ride(s)."
        )

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
    if 'self_check_in_allowed' in stage:
        item['selfCheckInAllowed'] = stage['self_check_in_allowed']
    if 'self_not_riding_allowed' in stage:
        item['selfNotRidingAllowed'] = stage['self_not_riding_allowed']
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
    tour_rider = {
        'riderId': item['rider_id'],
        'profileId': item['profile_id'],
        'status': item['status'],
        'qrCodeData': item['qr_code_data'],
        'registeredAt': item['registered_at'],
        'createdAt': item['created_at'],
        'updatedAt': item['updated_at'],
    }
    if item.get('exited_at') is not None:
        tour_rider['exitedAt'] = item['exited_at']
    return tour_rider


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
    }
    # Convert floats, if present, from generator snake_case to API field names
    if item.get('floats') is not None:
        ride['floats'] = [
            {
                'floatNo': f.get('float_no'),
                'floatToStage': f.get('float_to_stage'),
            }
            for f in item['floats']
        ]
    ride['createdAt'] = item['created_at']
    ride['updatedAt'] = item['updated_at']
    if 'self_check_in_allowed' in item:
        ride['selfCheckInAllowed'] = item['self_check_in_allowed']
    if 'self_quit_riding_allowed' in item:
        ride['selfQuitRidingAllowed'] = item['self_quit_riding_allowed']
    
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
        table_name = build_table_name(stack_name, table_type, tour_id=tour_id)
        try:
            table = get_table(dynamodb, stack_name, table_type, tour_id=tour_id)
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


def update_tour_status(dynamodb, stack_name, tour_id, status, self_quit_riding_allowed=None):
    """Update simulation-controlled tour fields in TourMaster."""
    table = get_table(dynamodb, stack_name, 'TourMaster')

    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    update_expression = 'SET #status = :status, updatedAt = :now'
    expression_names = {'#status': 'status'}
    expression_values = {':status': status, ':now': now}
    if self_quit_riding_allowed is not None:
        update_expression += ', selfQuitRidingAllowed = :selfQuitRidingAllowed'
        expression_values[':selfQuitRidingAllowed'] = self_quit_riding_allowed

    table.update_item(
        Key={'tourId': tour_id},
        UpdateExpression=update_expression,
        ExpressionAttributeNames=expression_names,
        ExpressionAttributeValues=expression_values,
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
    if mode not in ('ride_number_anchor', 'historical'):
        raise ValueError(f"Unsupported date strategy mode: {mode}")

    if mode == 'ride_number_anchor':
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


    if mode == 'historical':
        # Just use the explicit dates in the schedule; no dynamic resolution needed.
        print("Using historical schedule dates...")
        hist_start_date = strategy.get('start_date')
        if hist_start_date:
            hist_start_dt = date.fromisoformat(str(hist_start_date))
            print(f"  Historical start date: {hist_start_dt.isoformat()}")
        else:
            print("  Fatal: start_date not provided; using explicit schedule dates")
            exit(1)

        for idx, day_cfg in enumerate(schedule, 1):
            ride_day_number = int(day_cfg.get('day', idx))
            resolved = hist_start_dt + timedelta(days=ride_day_number - 1)
            day_cfg['date'] = resolved.isoformat()


def resolve_schedule_statuses(config, include_today_checkins=False):
    """
    Resolve schedule status from date strategy anchor ride.

        Rules:
            - day < anchor_ride_number: CLOSED
            - day == anchor_ride_number: STARTED when include_today_checkins is true,
                otherwise PLANNED
            - day > anchor_ride_number: PLANNED
    """
    rides_cfg = config.get('rides', {})
    strategy = rides_cfg.get('date_strategy') or {}
    schedule = rides_cfg.get('schedule', [])

    strategy_mode = strategy.get('mode')
    if strategy_mode == 'ride_number_anchor':
        anchor_ride = int(strategy.get('anchor_ride_number', 3))
        print(f" Anchor Ride Number mode is used")
        print("Resolving schedule statuses from anchor ride...")
        
        today_status = 'STARTED' if include_today_checkins else 'PLANNED'
        print(f"  Status strategy: ride {anchor_ride} is {today_status}")
    elif strategy_mode == 'historical':
        print(f" Resolving schedule statuses from historical dates...")


    for idx, day_cfg in enumerate(schedule, 1):
        ride_day_number = int(day_cfg.get('day', idx))
        if strategy_mode == 'historical' or ride_day_number < anchor_ride:
            day_cfg['status'] = 'CLOSED'
        elif ride_day_number == anchor_ride:
            day_cfg['status'] = 'STARTED' if include_today_checkins else 'PLANNED'
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


def run_personal_code_scenario(args, config, stack_name, region, seed):
    """Execute the shared-table personal code update scenario."""
    scenario = get_scenario_metadata(config)
    validate_personal_code_scenario(config)

    print_run_header(
        scenario.get('name', 'Unnamed'),
        stack_name,
        seed,
        args.dry_run,
    )

    _, dynamodb = create_dynamodb_session(region)
    rng = random.Random(seed)

    assignments = assign_personal_codes(
        dynamodb,
        stack_name,
        config,
        rng,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        output_file = os.path.join(args.output_dir, 'personal_code_updates.json')
        print(f"\nWriting JSON file to {output_file}")
        write_json(assignments, output_file)
    else:
        print("\nPersonal code loading complete.")

    print(f"\nAssigned {len(assignments)} personal code(s).")


def run_tour_data_scenario(args, config, stack_name, region, seed):
    """Execute the tour data generation scenario."""
    scenario = get_scenario_metadata(config)
    validate_tour_data_scenario(config)

    validate_status_configuration(config)
    resolve_schedule_dates(config)
    resolve_schedule_statuses(
        config,
        include_today_checkins=args.include_today_checkins,
    )
    validate_schedule_dates(config)

    tour_config = config['tour']
    options = config.get('options', {})
    tour_id = tour_config['tour_id']

    print_run_header(
        scenario.get('name', 'Unnamed'),
        stack_name,
        seed,
        args.dry_run,
        extra_lines=[
            f"Tour     : {tour_id}",
            f"Include today's check-ins : {args.include_today_checkins}",
            f"Today's check-ins only    : {args.today_checkins_only}",
        ],
    )

    validate_scenario(config)

    _, dynamodb = create_dynamodb_session(region)

    print('Fetching tour from TourMaster...')
    tour = fetch_tour(dynamodb, stack_name, tour_id)
    if not tour:
        print(f"  Error: Tour '{tour_id}' not found in {build_table_name(stack_name, 'TourMaster')}")
        sys.exit(1)
    print(f"  Found: {tour.get('name')} (status: {tour.get('status')})")

    print('Fetching rider profiles from RiderProfile...')
    # profiles = fetch_rider_profiles(dynamodb, stack_name)
    profiles = fetch_eligible_rider_profiles(dynamodb, stack_name, config, select_path='tour_riders')

    if not profiles:
        print(f"  Error: No profiles found in {build_table_name(stack_name, 'RiderProfile')}")
        sys.exit(1)
    print(f"  Found {len(profiles)} profiles")

    rider_count = config['tour_riders']['count']
    if rider_count > len(profiles):
        print(
            f"  Error: scenario requests {rider_count} riders but only "
            f"{len(profiles)} profiles available"
        )
        sys.exit(1)

    effective_clean_before_load = (
        options.get('clean_before_load') and not args.today_checkins_only
    )

    if (args.clean or args.clean_only or effective_clean_before_load) \
            and not args.dry_run:
        print('\nCleaning existing tour data...')
        clean_tour_data(dynamodb, stack_name, tour_id)

        if args.clean_only:
            print('\nClean complete.')
            return

    rng = random.Random(seed)

    print('\nSelecting tour riders from existing profiles...')
    tour_riders = select_tour_riders(profiles, rider_count, rng)
    print(f"  Selected {len(tour_riders)} riders (R1-R{len(tour_riders)})")

    print('Building rides...')
    rides_data = build_rides(config)
    rides = [rd['ride'] for rd in rides_data]
    print(f"  Built {len(rides)} rides")
    # Apply any rider exit directives from the schedule (mark TourRider items)
    exited = apply_rider_exits(rides_data, tour_riders, rng)
    if exited:
        print(f"  Exited riders: {len(exited)}")

    print('Generating check-ins...')
    checkins = generate_checkins(
        rides_data,
        tour_riders,
        rng,
        include_today_checkins=args.include_today_checkins,
        today_checkins_only=args.today_checkins_only,
    )
    print(f"  Generated {len(checkins)} check-in records")

    if args.dry_run:
        print(f"\nWriting JSON files to {args.output_dir}/")
        if not args.today_checkins_only:
            write_json(tour_riders, os.path.join(args.output_dir, 'tour_riders.json'))
            write_json(rides, os.path.join(args.output_dir, 'rides.json'))
        write_json(checkins, os.path.join(args.output_dir, 'checkins.json'))
    else:
        print('\nLoading data to DynamoDB...')

        ddb_checkins = to_dynamodb_items('CheckIn', checkins)

        if not args.today_checkins_only:
            ddb_tour_riders = to_dynamodb_items('TourRider', tour_riders)
            ddb_rides = to_dynamodb_items('Ride', rides)

            table_name = build_table_name(stack_name, 'TourRider', tour_id=tour_id)
            print(f"  Loading {len(tour_riders)} tour riders to {table_name}...")
            loaded, failed = load_to_dynamodb(dynamodb, table_name, ddb_tour_riders)
            print(f"    Loaded: {loaded}, Failed: {failed}")

            table_name = build_table_name(stack_name, 'Ride', tour_id=tour_id)
            print(f"  Loading {len(rides)} rides to {table_name}...")
            loaded, failed = load_to_dynamodb(dynamodb, table_name, ddb_rides)
            print(f"    Loaded: {loaded}, Failed: {failed}")
        else:
            print('  Skipping TourRider and Ride writes (--today-checkins-only)')

        table_name = build_table_name(stack_name, 'CheckIn', tour_id=tour_id)
        print(f"  Loading {len(checkins)} check-ins to {table_name}...")
        loaded, failed = load_to_dynamodb(dynamodb, table_name, ddb_checkins)
        print(f"    Loaded: {loaded}, Failed: {failed}")

        if options.get('update_tour_status', True):
            target_status = tour_config.get('target_status')
            if target_status:
                print(f"\n  Updating tour status to {target_status}...")
                update_tour_status(
                    dynamodb,
                    stack_name,
                    tour_id,
                    target_status,
                    tour_config.get('self_quit_riding_allowed'),
                )
                print('    Done')

    print_summary(tour_riders, rides_data, checkins)
    print('Data generation complete!')


# ============================================================================
# EVENT ENGINE SIMULATION (generic — event/activity/occurrence content is
# entirely scenario-config driven; nothing about a specific event is
# hardcoded here, only generic defaults for optional config fields)
# ============================================================================

EVENT_TABLE_TYPES = ['Event', 'EventOccurrence', 'EventActivityLogs', 'EventRegistration', 'Hotel', 'RoomAllocation']

EVENT_OCCURRENCE_STATUS_PLANNED = 'PLANNED'
EVENT_OCCURRENCE_STATUS_ACTIVE = 'ACTIVE'
EVENT_OCCURRENCE_STATUS_COMPLETED = 'COMPLETED'

EVENT_RECORD_OUTCOME_COMPLETED = 'COMPLETED'
EVENT_RECORD_OUTCOME_OPTED_OUT = 'OPTED_OUT'

ACTIVITY_CONFIG_DEFAULTS = {
    'enabled': True,
    'mandatory': False,
    'allowed_type_codes': [],
    'allow_opt_out': False,
    'prerequisite_activity_ids': [],
    'restrict_to_assigned_users': True,
    'variant_options': [],
    'notes': '',
}


def resolve_anchor_date(config):
    """Resolve the event scenario's 'today' anchor date, used as day_offset=0."""
    anchor_cfg = (config.get('date_strategy') or {}).get('anchor_date', 'today')
    if isinstance(anchor_cfg, str) and anchor_cfg.strip().lower() == 'today':
        return date.today()
    return date.fromisoformat(str(anchor_cfg))


def build_hotel_items(config):
    """Build Hotel-{tourId} items from the scenario's optional 'hotels' list."""
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    items = []
    for hotel_cfg in config.get('hotels') or []:
        items.append({
            'hotelId': hotel_cfg['hotel_id'],
            'name': hotel_cfg.get('name', hotel_cfg['hotel_id']),
            'city': hotel_cfg.get('city'),
            'address': hotel_cfg.get('address'),
            'contact': hotel_cfg.get('contact'),
            'notes': hotel_cfg.get('notes'),
            'createdAt': now,
            'updatedAt': now,
        })
    return [{k: v for k, v in item.items() if v is not None} for item in items]


def build_room_allocation_items(config, anchor_date, rider_ids):
    """
    Build RoomAllocation-{tourId} items from the scenario's optional
    'room_allocation' section, assigning riders round-robin into
    reciprocally-shared rooms of the configured capacity, one hotel per
    configured night.
    """
    room_cfg = config.get('room_allocation')
    if not room_cfg:
        return []

    room_capacity = int(room_cfg.get('room_capacity', 2))
    room_number_start = int(room_cfg.get('room_number_start', 201))
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    items = []
    for night_cfg in room_cfg['nights']:
        if 'day_offset' not in night_cfg or 'hotel_id' not in night_cfg:
            raise ValueError("room_allocation.nights entries require day_offset and hotel_id")

        stay_date = (anchor_date + timedelta(days=int(night_cfg['day_offset']))).isoformat()
        hotel_id = night_cfg['hotel_id']

        room_no = room_number_start
        for group_start in range(0, len(rider_ids), room_capacity):
            room_riders = rider_ids[group_start:group_start + room_capacity]
            for rider_id in room_riders:
                items.append({
                    'stayDate': stay_date,
                    'riderId': rider_id,
                    'hotelId': hotel_id,
                    'roomNo': str(room_no),
                    'roomCapacity': room_capacity,
                    'sharingWith': [r for r in room_riders if r != rider_id],
                    'source': 'MANUAL',
                    'createdAt': now,
                    'updatedAt': now,
                })
            room_no += 1

    return items


def build_activity_item(activity_cfg, context):
    """Convert one scenario-config activity entry into an Event.activities[] item."""
    merged = {**ACTIVITY_CONFIG_DEFAULTS, **activity_cfg}
    item = {
        'activityId': merged['activity_id'],
        'name': merged['name'],
        'sequenceNo': int(merged['sequence_no']),
        'enabled': bool(merged['enabled']),
        'mandatory': bool(merged['mandatory']),
        'allowedTypeCodes': list(merged['allowed_type_codes']),
        'allowOptOut': bool(merged['allow_opt_out']),
        'prerequisiteActivityIds': list(merged['prerequisite_activity_ids']),
        'restrictToAssignedUsers': bool(merged['restrict_to_assigned_users']),
        'variantOptions': list(merged['variant_options']),
        'notes': merged['notes'],
    }
    if 'self_service_allowed' in activity_cfg:
        item['selfServiceAllowed'] = activity_cfg['self_service_allowed']
    return item


def build_event_definition_item(event_cfg, event_index):
    """Convert one scenario-config event entry into an Event-{tourId} item."""
    context = f"events[{event_index}]"
    activities = [
        build_activity_item(activity_cfg, f"{context}.activities[{idx}]")
        for idx, activity_cfg in enumerate(event_cfg['activities'], 1)
    ]

    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return {
        'eventId': event_cfg['event_id'],
        'eventName': event_cfg['event_name'],
        'eventType': event_cfg['event_type'],
        'location': event_cfg['location'],
        'sequenceEnforced': bool(event_cfg['sequence_enforced']),
        'defaultAllowedTypeCodes': list(event_cfg['default_allowed_type_codes']),
        'registrationEnabled': bool(event_cfg.get('registration_enabled', False)),
        'selfServiceAllowed': bool(event_cfg.get('self_service_allowed', False)),
        'activities': activities,
        'createdAt': now,
        'updatedAt': now,
        'updatedBy': 'simulation-script',
    }


def build_occurrence_item(event_id, occurrence_cfg, anchor_date, seed_in_progress):
    """
    Convert one scenario-config occurrence entry into an EventOccurrence item.

    Status/timing is derived generically from day_offset relative to the
    anchor ("today") date:
      - day_offset < 0  -> COMPLETED (fully in the past)
      - day_offset == 0 -> PLANNED by default ("start of event", fresh for
        manual testing), or the configured in_progress status when
        seed_in_progress is requested and the occurrence has an
        'in_progress' block
      - day_offset > 0  -> PLANNED (future, untouched)

    Returns (item, meta) where meta carries day_offset/seq/linked_event_id
    for the second-pass linked-occurrence resolution and record generation.
    """
    day_offset = int(occurrence_cfg['day_offset'])
    seq = int(occurrence_cfg['seq'])
    occurrence_date = (anchor_date + timedelta(days=day_offset)).isoformat()
    date_seq = f"{occurrence_date}#{seq}"
    occurrence_id = f"{event_id}#{date_seq}"
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    status = EVENT_OCCURRENCE_STATUS_PLANNED
    started_at = None
    completed_at = None

    if day_offset < 0:
        status = EVENT_OCCURRENCE_STATUS_COMPLETED
        started_at = f"{occurrence_date}T06:00:00Z"
        completed_at = f"{occurrence_date}T20:00:00Z"
    elif day_offset == 0 and seed_in_progress and occurrence_cfg.get('in_progress'):
        status = occurrence_cfg['in_progress'].get('status', EVENT_OCCURRENCE_STATUS_ACTIVE)
        started_at = f"{occurrence_date}T06:00:00Z"

    item = {
        'eventId': event_id,
        'dateSeq': date_seq,
        'occurrenceId': occurrence_id,
        'date': occurrence_date,
        'seq': seq,
        'status': status,
        'activityOverrides': [],
        'restrictToAssignedUsers': bool(occurrence_cfg.get('restrict_to_assigned_users', True)),
        'startedAt': started_at,
        'completedAt': completed_at,
        'createdAt': now,
        'updatedAt': now,
        'updatedBy': 'simulation-script',
    }
    if 'self_service_allowed' in occurrence_cfg:
        item['selfServiceAllowed'] = occurrence_cfg['self_service_allowed']
    item = {k: v for k, v in item.items() if v is not None}

    meta = {
        'day_offset': day_offset,
        'seq': seq,
        'linked_event_id': occurrence_cfg.get('linked_event_id'),
    }
    return item, meta


def _sequenced_enabled_activities(event_item, up_to_activity_id=None):
    """Return the event's activities in sequence order, optionally truncated."""
    activities = sorted(
        (a for a in event_item['activities'] if a.get('enabled', True)),
        key=lambda a: a['sequenceNo'],
    )
    if up_to_activity_id is None:
        return activities
    activity_by_id = {a['activityId']: a for a in event_item['activities']}
    limit_seq = activity_by_id[up_to_activity_id]['sequenceNo']
    return [a for a in activities if a['sequenceNo'] <= limit_seq]


def _pick_variant(variant_options, variant_split, rng):
    """Pick a variant option, honouring an optional variant->ratio split."""
    if not variant_options:
        return None
    if not variant_split:
        return rng.choice(variant_options)
    roll = rng.random()
    cumulative = 0.0
    for variant, ratio in variant_split.items():
        cumulative += ratio
        if roll <= cumulative:
            return variant
    return variant_options[-1]


def _activity_scan_timestamp(occurrence_date, activity_seq, rng):
    """Build a deterministic-ish scan timestamp spread across an event day."""
    total_minutes = 360 + activity_seq * 15 + rng.randint(0, 10)
    hour, minute = divmod(total_minutes % (24 * 60), 60)
    second = rng.randint(0, 59)
    return f"{occurrence_date}T{hour:02d}:{minute:02d}:{second:02d}Z"


def build_activity_records_for_occurrence(
    event_item, occurrence_item, day_offset, rider_ids, occurrence_cfg, seed_in_progress, rng,
):
    """
    Generate EventActivityLogs items for one occurrence, entirely from its
    scenario-config 'progress' (past/completed occurrences) or 'in_progress'
    (today's occurrence, opt-in via --include-in-progress) block.

    Future/untouched occurrences and today's occurrence without seeding
    produce no records, leaving the occurrence available for manual
    QR-scan testing from its current state.
    """
    if day_offset < 0:
        return _build_full_progress_records(event_item, occurrence_item, rider_ids, occurrence_cfg, rng)

    if day_offset == 0 and seed_in_progress:
        in_progress_cfg = occurrence_cfg.get('in_progress')
        if in_progress_cfg:
            return _build_in_progress_records(
                event_item, occurrence_item, rider_ids, in_progress_cfg, rng,
            )

    return []


def _build_full_progress_records(event_item, occurrence_item, rider_ids, occurrence_cfg, rng):
    """Every rider completes the full activity sequence (historical occurrence)."""
    records = []
    activity_outcomes_cfg = (occurrence_cfg.get('progress') or {}).get('activity_outcomes', {})

    for activity in _sequenced_enabled_activities(event_item):
        outcome_cfg = activity_outcomes_cfg.get(activity['activityId'], {})
        opted_out_ratio = outcome_cfg.get('opted_out_ratio', 0) if activity.get('allowOptOut') else 0
        opted_out_count = round(opted_out_ratio * len(rider_ids))
        opted_out_riders = set(rng.sample(rider_ids, opted_out_count)) if opted_out_count else set()
        variant_split = outcome_cfg.get('variant_split')

        for rider_id in rider_ids:
            outcome = (
                EVENT_RECORD_OUTCOME_OPTED_OUT if rider_id in opted_out_riders
                else EVENT_RECORD_OUTCOME_COMPLETED
            )
            variant_selected = None
            if outcome == EVENT_RECORD_OUTCOME_COMPLETED and activity.get('variantOptions'):
                variant_selected = _pick_variant(activity['variantOptions'], variant_split, rng)
            timestamp = _activity_scan_timestamp(occurrence_item['date'], activity['sequenceNo'], rng)
            records.append(_build_activity_record(
                event_item, occurrence_item, activity, rider_id, timestamp, outcome, variant_selected,
            ))

    return records


def _build_in_progress_records(event_item, occurrence_item, rider_ids, in_progress_cfg, rng):
    """
    Distribute riders across "furthest activity reached" buckets so a tester
    can pick up manual scanning immediately for every rider not yet assigned
    a bucket (mirrors the ride check-in scenario's 'in_progress' shape).
    """
    records = []
    activity_distribution = in_progress_cfg.get('activity_distribution', {})
    available = list(rider_ids)
    rng.shuffle(available)

    for activity_id, count in activity_distribution.items():
        group_riders = available[:count]
        available = available[count:]
        activities_to_complete = _sequenced_enabled_activities(event_item, up_to_activity_id=activity_id)

        for rider_id in group_riders:
            for activity in activities_to_complete:
                timestamp = _activity_scan_timestamp(occurrence_item['date'], activity['sequenceNo'], rng)
                variant_selected = _pick_variant(activity.get('variantOptions'), None, rng)
                records.append(_build_activity_record(
                    event_item, occurrence_item, activity, rider_id, timestamp,
                    EVENT_RECORD_OUTCOME_COMPLETED, variant_selected,
                ))

    if available:
        print(
            f"  Note: {len(available)} rider(s) left with no activity records for "
            f"{occurrence_item['occurrenceId']} (available for manual scanning from the start)"
        )

    return records


def _build_activity_record(event_item, occurrence_item, activity, rider_id, timestamp, outcome, variant_selected):
    """Build a single EventActivityLogs item."""
    record = {
        'occurrenceId': occurrence_item['occurrenceId'],
        'recordId': f"{rider_id}#{activity['activityId']}#{timestamp}",
        'eventId': event_item['eventId'],
        'activityId': activity['activityId'],
        'activityName': activity['name'],
        'riderId': rider_id,
        'outcome': outcome,
        'variantSelected': variant_selected,
        'scannedBy': 'simulation-script',
        'method': 'QR_SCAN',
        'timestamp': timestamp,
        'syncedAt': timestamp,
        'isFlagged': False,
        'createdAt': timestamp,
    }
    allowed_type_codes = activity.get('allowedTypeCodes') or event_item.get('defaultAllowedTypeCodes') or []
    if allowed_type_codes:
        record['typeCode'] = allowed_type_codes[0]
    return {k: v for k, v in record.items() if v is not None}


def clean_event_tables(dynamodb, stack_name, tour_id):
    """Clean all data from the event-engine tour-specific tables."""
    for table_type in EVENT_TABLE_TYPES:
        table_name = build_table_name(stack_name, table_type, tour_id=tour_id)
        try:
            table = get_table(dynamodb, stack_name, table_type, tour_id=tour_id)
            deleted = clean_table(table)
            print(f"  Cleaned {table_name}: {deleted} items deleted")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                print(f"  Skipped {table_name}: table not found")
            else:
                raise


def run_event_data_scenario(args, config, stack_name, region, seed):
    """Execute the generic event-engine simulation scenario."""
    scenario = get_scenario_metadata(config)
    validate_event_data_scenario(config)

    tour_id = config['tour']['tour_id']
    anchor_date = resolve_anchor_date(config)
    seed_in_progress = args.include_in_progress or args.in_progress_only

    print_run_header(
        scenario.get('name', 'Unnamed'), stack_name, seed, args.dry_run,
        extra_lines=[
            f"Tour                   : {tour_id}",
            f"Anchor date ('today')  : {anchor_date.isoformat()}",
            f"Seed in-progress scans : {seed_in_progress}",
            f"In-progress only       : {args.in_progress_only}",
        ],
    )

    _, dynamodb = create_dynamodb_session(region)
    rng = random.Random(seed)

    print('Fetching tour from TourMaster...')
    tour = fetch_tour(dynamodb, stack_name, tour_id)
    if not tour:
        print(f"  Error: Tour '{tour_id}' not found in {build_table_name(stack_name, 'TourMaster')}")
        sys.exit(1)
    print(f"  Found: {tour.get('name')} (status: {tour.get('status')})")

    riders_cfg = config.get('riders', {})
    print('Fetching existing tour riders from TourRider...')
    rider_ids = fetch_tour_riders(
        dynamodb, stack_name, tour_id,
        status_in=riders_cfg.get('status_in', ['REGISTERED']),
        limit=riders_cfg.get('limit'),
    )
    if not rider_ids:
        print(
            "  Error: no matching riders found in TourRider table for this tour. "
            "Run a tour-data scenario (e.g. tot_2026.yaml) first."
        )
        sys.exit(1)
    print(f"  Using {len(rider_ids)} rider(s): {rider_ids[0]}..{rider_ids[-1]}")

    hotel_items = build_hotel_items(config)
    room_allocation_items = build_room_allocation_items(config, anchor_date, rider_ids)

    event_items = []
    occurrence_meta = []  # list of (event_item, occurrence_item, meta, occurrence_cfg)
    occurrences_by_key = {}

    for event_index, event_cfg in enumerate(config['events'], 1):
        event_item = build_event_definition_item(event_cfg, event_index)
        event_items.append(event_item)

        for occurrence_cfg in event_cfg['occurrences']:
            occurrence_item, meta = build_occurrence_item(
                event_item['eventId'], occurrence_cfg, anchor_date, seed_in_progress,
            )
            occurrences_by_key[(event_item['eventId'], meta['day_offset'], meta['seq'])] = occurrence_item
            occurrence_meta.append((event_item, occurrence_item, meta, occurrence_cfg))

    # Second pass: resolve linkedOccurrenceRef pairs (e.g. Baggage Loading <-> Unloading)
    for _, occurrence_item, meta, _ in occurrence_meta:
        linked_event_id = meta.get('linked_event_id')
        if not linked_event_id:
            continue
        linked = occurrences_by_key.get((linked_event_id, meta['day_offset'], meta['seq']))
        if linked:
            occurrence_item['linkedOccurrenceRef'] = linked['occurrenceId']
        else:
            print(
                f"  Warning: no matching occurrence in '{linked_event_id}' for "
                f"day_offset={meta['day_offset']}, seq={meta['seq']} to link with "
                f"{occurrence_item['occurrenceId']}"
            )

    activity_records = []
    for event_item, occurrence_item, meta, occurrence_cfg in occurrence_meta:
        if args.in_progress_only and meta['day_offset'] != 0:
            continue
        activity_records.extend(build_activity_records_for_occurrence(
            event_item, occurrence_item, meta['day_offset'], rider_ids, occurrence_cfg,
            seed_in_progress, rng,
        ))

    occurrences_to_write = [
        occurrence_item for _, occurrence_item, meta, _ in occurrence_meta
        if not args.in_progress_only or meta['day_offset'] == 0
    ]

    print(f"Built {len(event_items)} event definition(s), {len(occurrences_to_write)} occurrence(s), "
          f"{len(activity_records)} activity record(s)")

    if args.dry_run:
        print(f"\nWriting JSON files to {args.output_dir}/")
        if not args.in_progress_only:
            write_json(event_items, os.path.join(args.output_dir, 'events.json'))
            write_json(hotel_items, os.path.join(args.output_dir, 'hotels.json'))
            write_json(room_allocation_items, os.path.join(args.output_dir, 'room_allocations.json'))
        write_json(occurrences_to_write, os.path.join(args.output_dir, 'event_occurrences.json'))
        write_json(activity_records, os.path.join(args.output_dir, 'event_activity_records.json'))
        print('\nDry run complete. No data written to DynamoDB.')
        return

    options = config.get('options', {})
    if options.get('clean_before_load') and not args.in_progress_only:
        print('\nCleaning existing event-engine data...')
        clean_event_tables(dynamodb, stack_name, tour_id)

    print('\nLoading data to DynamoDB...')

    if not args.in_progress_only:
        table_name = build_table_name(stack_name, 'Hotel', tour_id=tour_id)
        print(f"  Loading {len(hotel_items)} hotel(s) to {table_name}...")
        loaded, failed = load_to_dynamodb(dynamodb, table_name, hotel_items)
        print(f"    Loaded: {loaded}, Failed: {failed}")

        table_name = build_table_name(stack_name, 'RoomAllocation', tour_id=tour_id)
        print(f"  Loading {len(room_allocation_items)} room allocation(s) to {table_name}...")
        loaded, failed = load_to_dynamodb(dynamodb, table_name, room_allocation_items)
        print(f"    Loaded: {loaded}, Failed: {failed}")

        table_name = build_table_name(stack_name, 'Event', tour_id=tour_id)
        print(f"  Loading {len(event_items)} event definition(s) to {table_name}...")
        loaded, failed = load_to_dynamodb(dynamodb, table_name, event_items)
        print(f"    Loaded: {loaded}, Failed: {failed}")
    else:
        print('  Skipping Event/Hotel/RoomAllocation writes (--in-progress-only)')

    table_name = build_table_name(stack_name, 'EventOccurrence', tour_id=tour_id)
    print(f"  Loading {len(occurrences_to_write)} occurrence(s) to {table_name}...")
    loaded, failed = load_to_dynamodb(dynamodb, table_name, occurrences_to_write)
    print(f"    Loaded: {loaded}, Failed: {failed}")

    table_name = build_table_name(stack_name, 'EventActivityLogs', tour_id=tour_id)
    print(f"  Loading {len(activity_records)} activity record(s) to {table_name}...")
    loaded, failed = load_to_dynamodb(dynamodb, table_name, activity_records)
    print(f"    Loaded: {loaded}, Failed: {failed}")

    print('\nEvent data generation complete!')


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

  # Include today's check-ins
  python scripts/simulate/generate_data.py \\
      --scenario scripts/simulate/scenarios/tot_2026.yaml --include-today-checkins

  # Generate check-ins only for today's ride
  python scripts/simulate/generate_data.py \\
      --scenario scripts/simulate/scenarios/tot_2026.yaml --today-checkins-only

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
    parser.add_argument(
        '--include-today-checkins', action='store_true',
        help=(
            "Generate check-ins for today's ride as well. "
            "Default is to skip today's ride check-ins."
        ),
    )
    parser.add_argument(
        '--today-checkins-only', action='store_true',
        help=(
            "Generate/load check-ins for today's ride only "
            "(does not write TourRider or Ride data)."
        ),
    )
    parser.add_argument(
        '--include-in-progress', action='store_true',
        help=(
            "For event_data_generation scenarios: seed today's occurrence(s) "
            "with the partial activity records from the scenario's 'in_progress' "
            "config, instead of leaving them freshly PLANNED with no scans."
        ),
    )
    parser.add_argument(
        '--in-progress-only', action='store_true',
        help=(
            "For event_data_generation scenarios: only (re)populate today's "
            "occurrence(s) and their in-progress activity records; skips "
            "event/hotel/room-allocation and historical-occurrence writes. "
            "Implies --include-in-progress."
        ),
    )

    parser.add_argument(
        '--debug-enabled', action='store_true',
        help='Enable debug outputs for verification.',
    )

    args = parser.parse_args()
    DEBUG_ENABLED = args.debug_enabled

    if args.today_checkins_only and args.clean_only:
        parser.error('--today-checkins-only cannot be combined with --clean-only')

    if args.today_checkins_only and args.clean:
        parser.error('--today-checkins-only cannot be combined with --clean')

    if args.today_checkins_only:
        args.include_today_checkins = True

    if args.in_progress_only and args.clean_only:
        parser.error('--in-progress-only cannot be combined with --clean-only')

    if args.in_progress_only and args.clean:
        parser.error('--in-progress-only cannot be combined with --clean')

    if args.in_progress_only:
        args.include_in_progress = True

    # Load scenario
    with open(args.scenario) as f:
        config = yaml.safe_load(f)

    aws_config = config.get('aws', {})
    stack_name = aws_config.get('stack_name', 'dev')
    region = args.region or aws_config.get('region')
    seed = config.get('options', {}).get('seed', 42)

    scenario_type = get_scenario_type(config)
    if scenario_type == SCENARIO_TYPE_PERSONAL_CODE:
        run_personal_code_scenario(args, config, stack_name, region, seed)
        return

    if scenario_type == SCENARIO_TYPE_TOUR_DATA:
        run_tour_data_scenario(args, config, stack_name, region, seed)
        return

    if scenario_type == SCENARIO_TYPE_EVENT_DATA:
        run_event_data_scenario(args, config, stack_name, region, seed)
        return

    raise ValueError(f"Unsupported scenario.type: {scenario_type}")


if __name__ == '__main__':
    main()
