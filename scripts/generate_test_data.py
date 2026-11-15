#!/usr/bin/env python3
"""
Generate test data for a tour from a YAML scenario template.

This script creates realistic test data in DynamoDB tables for development
and testing. It generates rider profiles, tour rider registrations, rides,
and check-in records based on a configurable scenario template.

The scenario template (YAML file) defines:
- Number of rider profiles and their demographics
- Number of tour riders to register
- Ride configurations (days, stages, status)
- Check-in scenarios (not riding, quit riding, finished, in-progress)

Usage:
    # Generate test data
    python scripts/generate_test_data.py \\
        --scenario scripts/test_data/scenario_tot_2026.yaml \\
        --stack-name dev

    # Dry run (generate and validate without uploading)
    python scripts/generate_test_data.py \\
        --scenario scripts/test_data/scenario_tot_2026.yaml \\
        --stack-name dev --dry-run

    # With explicit region and seed
    python scripts/generate_test_data.py \\
        --scenario scripts/test_data/scenario_tot_2026.yaml \\
        --stack-name dev --region ap-south-1 --seed 42

Prerequisites:
    - AWS CLI configured with valid credentials
    - Tour must be provisioned (tour-specific tables must exist)
    - Python packages: boto3, pyyaml
"""

import argparse
import random
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import boto3
import yaml
from botocore.exceptions import ClientError


# =============================================================================
# NAME POOLS FOR PROFILE GENERATION
# =============================================================================

INDIAN_MALE_FIRST_NAMES = [
    'Aarav', 'Aditya', 'Ajay', 'Amit', 'Anand', 'Anil', 'Arjun', 'Arun',
    'Ashok', 'Balaji', 'Bharath', 'Deepak', 'Dinesh', 'Ganesh', 'Gopal',
    'Hari', 'Jayesh', 'Karthik', 'Kiran', 'Kishore', 'Mahesh', 'Manoj',
    'Mohan', 'Naveen', 'Nikhil', 'Nitin', 'Prabhu', 'Prakash', 'Prasad',
    'Rahul', 'Rajesh', 'Ravi', 'Rohit', 'Sachin', 'Sanjay', 'Shankar',
    'Srikanth', 'Sunil', 'Suresh', 'Venkatesh', 'Vijay', 'Vikram', 'Vinod',
    'Vivek', 'Yash',
]

INDIAN_FEMALE_FIRST_NAMES = [
    'Anjali', 'Anita', 'Asha', 'Deepa', 'Divya', 'Gayathri', 'Hema',
    'Indira', 'Jaya', 'Kavita', 'Lakshmi', 'Meena', 'Nandini', 'Neha',
    'Nisha', 'Padma', 'Pooja', 'Priya', 'Radha', 'Rekha', 'Sangeetha',
    'Sarala', 'Sunita', 'Swati', 'Uma', 'Vani', 'Vidya',
]

INDIAN_LAST_NAMES = [
    'Agarwal', 'Bhat', 'Chandra', 'Das', 'Desai', 'Gupta', 'Hegde',
    'Iyer', 'Joshi', 'Kapoor', 'Kumar', 'Menon', 'Mishra', 'Nair',
    'Patel', 'Pillai', 'Rao', 'Reddy', 'Saxena', 'Sharma', 'Singh',
    'Srinivasan', 'Subramanian', 'Tiwari', 'Verma',
]

NON_INDIAN_MALE_FIRST_NAMES = [
    'Charles', 'David', 'James', 'Michael', 'Richard', 'Robert', 'Thomas',
    'William',
]

NON_INDIAN_FEMALE_FIRST_NAMES = [
    'Charlotte', 'Emma', 'Isabella', 'Mia', 'Olivia', 'Sophia',
]

NON_INDIAN_LAST_NAMES = [
    'Anderson', 'Brown', 'Davis', 'Johnson', 'Jones', 'Miller', 'Smith',
    'Taylor', 'Williams', 'Wilson',
]


# =============================================================================
# SCENARIO LOADING AND VALIDATION
# =============================================================================

def load_scenario(file_path):
    """Load and return YAML scenario template."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Error: Scenario file '{file_path}' not found.")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Error: Invalid YAML in '{file_path}': {e}")
        sys.exit(1)


def validate_scenario(scenario):
    """Validate scenario template has required fields and consistent counts."""
    required_top = ['tour', 'rider_profiles', 'tour_riders', 'default_stages', 'rides']
    for field in required_top:
        if field not in scenario:
            print(f"Error: Missing required field '{field}' in scenario template.")
            sys.exit(1)

    total_riders = scenario['tour_riders']['total']
    total_profiles = scenario['rider_profiles']['total_pool']

    if total_riders > total_profiles:
        print(f"Error: tour_riders.total ({total_riders}) > "
              f"rider_profiles.total_pool ({total_profiles})")
        sys.exit(1)

    non_indian_riders = scenario['tour_riders'].get('non_indian_count', 0)
    non_indian_profiles = scenario['rider_profiles'].get('non_indian_count', 0)
    if non_indian_riders > non_indian_profiles:
        print(f"Error: tour_riders.non_indian_count ({non_indian_riders}) > "
              f"rider_profiles.non_indian_count ({non_indian_profiles})")
        sys.exit(1)

    # Validate check-in scenario counts per ride
    for ride_def in scenario['rides']:
        if 'checkin_scenario' not in ride_def:
            continue
        cs = ride_def['checkin_scenario']
        not_riding = cs.get('not_riding', 0)
        quit_count = sum(g['count'] for g in cs.get('quit_groups', []))
        finished = cs.get('finished', 0)
        in_progress = sum(ip['count'] for ip in cs.get('in_progress', []))

        if finished == 'rest':
            accounted = not_riding + quit_count + in_progress
            if accounted > total_riders:
                print(f"Error: Day {ride_def['day']} — check-in counts ({accounted}) "
                      f"exceed total riders ({total_riders})")
                sys.exit(1)
        else:
            accounted = not_riding + quit_count + finished + in_progress
            if accounted != total_riders:
                print(f"Error: Day {ride_def['day']} — check-in counts ({accounted}) "
                      f"!= total riders ({total_riders})")
                sys.exit(1)

    print("  Scenario validation passed.")


# =============================================================================
# PROFILE GENERATION
# =============================================================================

def _generate_phone(rng, country_code='+91'):
    """Generate a random phone number."""
    if country_code == '+91':
        first = rng.choice(['7', '8', '9'])
        rest = ''.join(str(rng.randint(0, 9)) for _ in range(9))
        return f"{country_code}{first}{rest}"
    area = ''.join(str(rng.randint(2, 9)) for _ in range(3))
    number = ''.join(str(rng.randint(0, 9)) for _ in range(7))
    return f"{country_code}{area}{number}"


def generate_profiles(config, rng):
    """
    Generate rider profile items for DynamoDB.

    Returns:
        tuple: (profiles_list, categories_dict)
            profiles_list: List of profile dicts (DynamoDB items)
            categories_dict: Dict mapping category -> list of profileIds
    """
    total = config['rider_profiles']['total_pool']
    non_indian = config['rider_profiles']['non_indian_count']
    male_pct = config['rider_profiles']['male_percentage']

    indian_count = total - non_indian
    indian_male = int(indian_count * male_pct / 100)
    indian_female = indian_count - indian_male
    non_indian_male = int(non_indian * male_pct / 100)
    non_indian_female = non_indian - non_indian_male

    profiles = []
    categories = {
        'indian_male': [], 'indian_female': [],
        'non_indian_male': [], 'non_indian_female': [],
    }
    used_names = set()
    profile_num = 1
    now = '2026-01-01T00:00:00Z'

    def _make_profile(first, last, is_indian, category):
        nonlocal profile_num
        full_name = f"{first} {last}"
        if full_name in used_names:
            return False
        used_names.add(full_name)

        pid = f"P{profile_num:03d}"
        profile_num += 1
        cc = '+91' if is_indian else '+1'

        ec_names = INDIAN_MALE_FIRST_NAMES if is_indian else NON_INDIAN_MALE_FIRST_NAMES
        ec_first = rng.choice(ec_names)

        profiles.append({
            'profileId': pid,
            'name': full_name,
            'email': f"{first.lower()}.{last.lower()}{rng.randint(1, 99)}@example.com",
            'phone': _generate_phone(rng, cc),
            'emergencyContactName': f"{ec_first} {last}",
            'emergencyContactPhone': _generate_phone(rng, cc),
            'createdAt': now,
            'updatedAt': now,
        })
        categories[category].append(pid)
        return True

    # Generate each category
    _fill_category(rng, indian_male, INDIAN_MALE_FIRST_NAMES,
                   INDIAN_LAST_NAMES, True, 'indian_male', _make_profile)
    _fill_category(rng, indian_female, INDIAN_FEMALE_FIRST_NAMES,
                   INDIAN_LAST_NAMES, True, 'indian_female', _make_profile)
    _fill_category(rng, non_indian_male, NON_INDIAN_MALE_FIRST_NAMES,
                   NON_INDIAN_LAST_NAMES, False, 'non_indian_male', _make_profile)
    _fill_category(rng, non_indian_female, NON_INDIAN_FEMALE_FIRST_NAMES,
                   NON_INDIAN_LAST_NAMES, False, 'non_indian_female', _make_profile)

    return profiles, categories


def _fill_category(rng, count, first_names, last_names, is_indian, category,
                   make_profile_fn):
    """Generate profiles for a specific category."""
    generated = 0
    attempts = 0
    max_attempts = count * 20
    while generated < count and attempts < max_attempts:
        first = rng.choice(first_names)
        last = rng.choice(last_names)
        if make_profile_fn(first, last, is_indian, category):
            generated += 1
        attempts += 1
    if generated < count:
        print(f"  Warning: Could only generate {generated}/{count} profiles "
              f"for category '{category}' (name pool exhausted)")


# =============================================================================
# TOUR RIDER SELECTION
# =============================================================================

def select_tour_riders(profiles, categories, config, rng):
    """
    Select riders from profiles pool and create tour rider records.

    Returns:
        list: Tour rider DynamoDB items
    """
    total_riders = config['tour_riders']['total']
    non_indian_needed = config['tour_riders'].get('non_indian_count', 0)

    # Collect profile IDs by nationality
    non_indian_pids = categories['non_indian_male'] + categories['non_indian_female']
    indian_pids = categories['indian_male'] + categories['indian_female']

    selected_pids = []

    # Pick non-Indian riders
    pick_non_indian = min(non_indian_needed, len(non_indian_pids))
    selected_pids.extend(rng.sample(non_indian_pids, pick_non_indian))

    # Pick remaining from Indian pool
    remaining = total_riders - len(selected_pids)
    selected_pids.extend(rng.sample(indian_pids, min(remaining, len(indian_pids))))

    rng.shuffle(selected_pids)

    now = '2026-01-15T00:00:00Z'
    tour_riders = []
    for i, pid in enumerate(selected_pids, 1):
        rider_id = f"R{i}"
        tour_riders.append({
            'riderId': rider_id,
            'profileId': pid,
            'status': 'ACTIVE',
            'qrCodeData': rider_id,
            'registeredAt': now,
            'createdAt': now,
            'updatedAt': now,
        })

    return tour_riders


# =============================================================================
# RIDE GENERATION
# =============================================================================

def generate_rides(config):
    """
    Generate ride records based on scenario configuration.

    Returns:
        tuple: (rides_list, ride_scenario_map)
            rides_list: List of ride DynamoDB items
            ride_scenario_map: Dict mapping rideId -> checkin_scenario dict
    """
    tour_start = datetime.strptime(config['tour']['start_date'], '%Y-%m-%d')
    default_stages = config['default_stages']
    rides = []
    ride_scenarios = {}
    ride_num = 1

    for ride_def in config['rides']:
        day = ride_def['day']
        rides_per_day = ride_def.get('rides_per_day', 1)
        status = ride_def.get('status', 'PLANNED')
        flag_off = ride_def.get('flag_off_time', '07:00')
        ride_date = (tour_start + timedelta(days=day)).strftime('%Y-%m-%d')

        for sub_ride in range(rides_per_day):
            ride_id = f"RIDE{ride_num:03d}"

            # Build stages
            stages = []
            total_dist = ride_def.get('total_distance', 100.0)
            num_stages = len(default_stages)
            for idx, sdef in enumerate(default_stages):
                sn = idx
                stage_position = idx + 1
                if sn == 0:
                    loc = ride_def.get('start_location', f'City {day}')
                    dist = 0.0
                elif sdef['type'] == 'FINISH':
                    loc = ride_def.get('finish_location', f'City {day + 1}')
                    dist = total_dist
                else:
                    loc = f"{sdef['name']} - Km {round(stage_position * total_dist / num_stages)}"
                    dist = round(stage_position * total_dist / num_stages, 1)

                stages.append({
                    'stageId': f"{ride_id}-S{sn:03d}",
                    'stageNumber': sn,
                    'type': sdef['type'],
                    'name': sdef['name'],
                    'location': loc,
                    'distanceFromStart': Decimal(str(dist)),
                })

            # Ride name
            name = f"Day {day}" if rides_per_day == 1 else f"Day {day} Ride {sub_ride + 1}"

            # Flag-off time for subsequent rides on same day
            if sub_ride > 0:
                base_h = int(flag_off.split(':')[0])
                current_flag_off = f"{base_h + 4 * sub_ride:02d}:00"
            else:
                current_flag_off = flag_off

            now = '2026-02-01T00:00:00Z'
            ride_item = {
                'rideId': ride_id,
                'date': ride_date,
                'rideNo': ride_num,
                'name': name,
                'startLocation': ride_def.get('start_location', f'City {day}'),
                'finishLocation': ride_def.get('finish_location', f'City {day + 1}'),
                'totalDistance': Decimal(str(total_dist)),
                'flagOffTime': current_flag_off,
                'status': status,
                'stages': stages,
                'description': f"Ride {ride_num} - {name}",
                'createdAt': now,
                'updatedAt': now,
            }

            if status == 'COMPLETED':
                ride_item['startedAt'] = f"{ride_date}T{current_flag_off}:00Z"
                ride_item['completedAt'] = f"{ride_date}T18:00:00Z"
            elif status == 'ACTIVE':
                ride_item['startedAt'] = f"{ride_date}T{current_flag_off}:00Z"

            rides.append(ride_item)

            # Map scenario for check-in generation
            if 'checkin_scenario' in ride_def:
                ride_scenarios[ride_id] = {
                    'checkin_scenario': ride_def['checkin_scenario'],
                    'ride_date': ride_date,
                    'flag_off_time': current_flag_off,
                    'stages': stages,
                }

            ride_num += 1

    return rides, ride_scenarios


# =============================================================================
# CHECK-IN GENERATION
# =============================================================================

def _make_timestamp(ride_date, base_hour, rider_num):
    """Generate a deterministic timestamp for a rider at a stage."""
    offset = (rider_num - 1) * 30  # 30-second intervals
    minutes = offset // 60
    seconds = offset % 60
    return f"{ride_date}T{base_hour:02d}:{minutes:02d}:{seconds:02d}Z"


def _stage_base_hour(flag_off_time, stage_number):
    """Calculate base hour for a given stage."""
    flag_off_hour = int(flag_off_time.split(':')[0])
    return flag_off_hour + stage_number * 2


def generate_checkins(ride_scenarios, tour_riders, config, rng):
    """
    Generate check-in records based on ride scenarios.

    Returns:
        list: CheckIn DynamoDB items
    """
    all_checkins = []
    rider_ids = [r['riderId'] for r in tour_riders]
    total_riders = len(rider_ids)

    for ride_id, scenario in ride_scenarios.items():
        cs = scenario['checkin_scenario']
        ride_date = scenario['ride_date']
        flag_off = scenario['flag_off_time']
        stages = scenario['stages']

        # Shuffle riders for random category assignment (deterministic with seed)
        shuffled = rider_ids[:]
        rng.shuffle(shuffled)
        idx = 0

        # --- Not Riding ---
        nr_count = cs.get('not_riding', 0)
        nr_riders = shuffled[idx:idx + nr_count]
        idx += nr_count

        nr_hour = max(int(flag_off.split(':')[0]) - 1, 0)
        for rider_id in nr_riders:
            rnum = int(rider_id[1:])
            ts = _make_timestamp(ride_date, nr_hour, rnum)
            all_checkins.append({
                'rideId': ride_id,
                'checkInId': f"{rider_id}#000#{ts}",
                'riderId': rider_id,
                'stageNumber': 0,
                'stageId': stages[0]['stageId'],
                'timestamp': ts,
                'checkedInBy': 'admin-001',
                'method': 'MANUAL',
                'isNotRiding': True,
                'isQuitRiding': False,
                'isManualEntry': True,
                'status': 'NOT_RIDING',
                'createdAt': ts,
            })

        # --- Quit Groups ---
        for qg in cs.get('quit_groups', []):
            after_stage = qg['after_stage']
            count = qg['count']
            quit_riders = shuffled[idx:idx + count]
            idx += count

            for rider_id in quit_riders:
                rnum = int(rider_id[1:])

                # Normal check-ins at stages 0 through after_stage
                for stage in stages[:after_stage + 1]:
                    sn = stage['stageNumber']
                    bh = _stage_base_hour(flag_off, sn)
                    ts = _make_timestamp(ride_date, bh, rnum)
                    all_checkins.append({
                        'rideId': ride_id,
                        'checkInId': f"{rider_id}#{sn:03d}#{ts}",
                        'riderId': rider_id,
                        'stageNumber': sn,
                        'stageId': stage['stageId'],
                        'timestamp': ts,
                        'checkedInBy': 'system',
                        'method': 'QR_SCAN',
                        'isNotRiding': False,
                        'isQuitRiding': False,
                        'isManualEntry': False,
                        'status': 'CHECKED_IN',
                        'createdAt': ts,
                    })

                # Quit riding check-in at the quit stage (1 hour later)
                quit_bh = _stage_base_hour(flag_off, after_stage) + 1
                quit_ts = _make_timestamp(ride_date, quit_bh, rnum)
                quit_stage = stages[after_stage]
                all_checkins.append({
                    'rideId': ride_id,
                    'checkInId': f"{rider_id}#{after_stage:03d}#{quit_ts}",
                    'riderId': rider_id,
                    'stageNumber': after_stage,
                    'stageId': quit_stage['stageId'],
                    'timestamp': quit_ts,
                    'checkedInBy': 'admin-001',
                    'method': 'MANUAL',
                    'isNotRiding': False,
                    'isQuitRiding': True,
                    'isManualEntry': True,
                    'status': 'QUIT_RIDING',
                    'createdAt': quit_ts,
                })

        # --- Finished ---
        finished = cs.get('finished', 0)
        in_progress_count = sum(ip['count'] for ip in cs.get('in_progress', []))
        if finished == 'rest':
            finished_count = total_riders - idx - in_progress_count
        else:
            finished_count = finished

        finished_riders = shuffled[idx:idx + finished_count]
        idx += finished_count

        for rider_id in finished_riders:
            rnum = int(rider_id[1:])
            for stage in stages:
                sn = stage['stageNumber']
                bh = _stage_base_hour(flag_off, sn)
                ts = _make_timestamp(ride_date, bh, rnum)
                all_checkins.append({
                    'rideId': ride_id,
                    'checkInId': f"{rider_id}#{sn:03d}#{ts}",
                    'riderId': rider_id,
                    'stageNumber': sn,
                    'stageId': stage['stageId'],
                    'timestamp': ts,
                    'checkedInBy': 'system',
                    'method': 'QR_SCAN',
                    'isNotRiding': False,
                    'isQuitRiding': False,
                    'isManualEntry': False,
                    'status': 'CHECKED_IN',
                    'createdAt': ts,
                })

        # --- In Progress ---
        for ipg in cs.get('in_progress', []):
            at_stage = ipg['at_stage']
            count = ipg['count']
            ip_riders = shuffled[idx:idx + count]
            idx += count

            for rider_id in ip_riders:
                rnum = int(rider_id[1:])
                # Check-ins from stage 0 through at_stage
                for stage in stages[:at_stage + 1]:
                    sn = stage['stageNumber']
                    bh = _stage_base_hour(flag_off, sn)
                    ts = _make_timestamp(ride_date, bh, rnum)
                    all_checkins.append({
                        'rideId': ride_id,
                        'checkInId': f"{rider_id}#{sn:03d}#{ts}",
                        'riderId': rider_id,
                        'stageNumber': sn,
                        'stageId': stage['stageId'],
                        'timestamp': ts,
                        'checkedInBy': 'system',
                        'method': 'QR_SCAN',
                        'isNotRiding': False,
                        'isQuitRiding': False,
                        'isManualEntry': False,
                        'status': 'CHECKED_IN',
                        'createdAt': ts,
                    })

        # Verify all riders were assigned
        if idx != total_riders:
            print(f"  Warning: Ride {ride_id} — assigned {idx}/{total_riders} riders")

    return all_checkins


# =============================================================================
# DYNAMODB UPLOAD
# =============================================================================

def _upload_items(table, items, table_name):
    """Upload items to a DynamoDB table using batch writer."""
    loaded = 0
    failed = 0
    with table.batch_writer() as batch:
        for i, item in enumerate(items, 1):
            try:
                batch.put_item(Item=item)
                loaded += 1
            except ClientError as e:
                failed += 1
                print(f"    Failed item {i}: {e.response['Error']['Message']}")
            if i % 100 == 0:
                print(f"    Progress: {i}/{len(items)}...")
    return loaded, failed


def _get_table(dynamodb, table_name):
    """Get and verify a DynamoDB table exists."""
    table = dynamodb.Table(table_name)
    try:
        table.load()
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            return None
        raise
    return table


def upload_data(session, stack_name, tour_id, profiles, riders, rides, checkins):
    """Upload all generated data to DynamoDB tables."""
    dynamodb = session.resource('dynamodb')
    total_failed = 0

    # 1. Rider Profiles → shared RiderProfile table
    profile_tbl = f"{stack_name}-RiderProfile"
    print(f"\n  Loading {len(profiles)} rider profiles → {profile_tbl}")
    table = _get_table(dynamodb, profile_tbl)
    if table:
        loaded, failed = _upload_items(table, profiles, profile_tbl)
        total_failed += failed
        print(f"    Done: {loaded} loaded, {failed} failed")
    else:
        print(f"    Warning: Table '{profile_tbl}' not found — skipping profiles.")

    # 2. Tour Riders → TourRider-{tourId}
    rider_tbl = f"{stack_name}-TourRider-{tour_id}"
    print(f"  Loading {len(riders)} tour riders → {rider_tbl}")
    table = _get_table(dynamodb, rider_tbl)
    if not table:
        print(f"    Error: Table '{rider_tbl}' not found. Was the tour provisioned?")
        sys.exit(1)
    loaded, failed = _upload_items(table, riders, rider_tbl)
    total_failed += failed
    print(f"    Done: {loaded} loaded, {failed} failed")

    # 3. Rides → Ride-{tourId}
    ride_tbl = f"{stack_name}-Ride-{tour_id}"
    print(f"  Loading {len(rides)} rides → {ride_tbl}")
    table = _get_table(dynamodb, ride_tbl)
    if not table:
        print(f"    Error: Table '{ride_tbl}' not found. Was the tour provisioned?")
        sys.exit(1)
    loaded, failed = _upload_items(table, rides, ride_tbl)
    total_failed += failed
    print(f"    Done: {loaded} loaded, {failed} failed")

    # 4. Check-Ins → CheckIn-{tourId}
    checkin_tbl = f"{stack_name}-CheckIn-{tour_id}"
    print(f"  Loading {len(checkins)} check-ins → {checkin_tbl}")
    table = _get_table(dynamodb, checkin_tbl)
    if not table:
        print(f"    Error: Table '{checkin_tbl}' not found. Was the tour provisioned?")
        sys.exit(1)
    loaded, failed = _upload_items(table, checkins, checkin_tbl)
    total_failed += failed
    print(f"    Done: {loaded} loaded, {failed} failed")

    return total_failed


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Generate test data for a tour from a YAML scenario template',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate and upload test data
  python scripts/generate_test_data.py \\
      --scenario scripts/test_data/scenario_tot_2026.yaml \\
      --stack-name dev

  # Dry run — generate data and show summary without uploading
  python scripts/generate_test_data.py \\
      --scenario scripts/test_data/scenario_tot_2026.yaml \\
      --stack-name dev --dry-run

  # With explicit region and reproducible seed
  python scripts/generate_test_data.py \\
      --scenario scripts/test_data/scenario_tot_2026.yaml \\
      --stack-name dev --region ap-south-1 --seed 99
        """
    )

    parser.add_argument(
        '--scenario', required=True,
        help='Path to YAML scenario template file'
    )
    parser.add_argument(
        '--stack-name', required=True,
        help='CloudFormation stack name (e.g., dev, test)'
    )
    parser.add_argument(
        '--region', default=None,
        help='AWS region (default: from AWS config)'
    )
    parser.add_argument(
        '--seed', type=int, default=None,
        help='Random seed (overrides scenario seed)'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Generate data and show summary without uploading to DynamoDB'
    )

    args = parser.parse_args()

    # Load and validate scenario
    print("\n=== Test Data Generation ===\n")
    print("Loading scenario...")
    scenario = load_scenario(args.scenario)
    validate_scenario(scenario)

    # Seed
    seed = args.seed if args.seed is not None else scenario.get('scenario', {}).get('seed', 42)
    rng = random.Random(seed)
    tour_id = scenario['tour']['tour_id']

    print(f"\n  Scenario : {scenario.get('scenario', {}).get('name', 'N/A')}")
    print(f"  Tour     : {tour_id}")
    print(f"  Stack    : {args.stack_name}")
    print(f"  Seed     : {seed}")
    print(f"  Dry run  : {args.dry_run}")

    # Generate data
    print("\nGenerating data...")

    profiles, categories = generate_profiles(scenario, rng)
    print(f"  Rider profiles : {len(profiles)}")

    tour_riders = select_tour_riders(profiles, categories, scenario, rng)
    print(f"  Tour riders    : {len(tour_riders)}")

    rides, ride_scenarios = generate_rides(scenario)
    print(f"  Rides          : {len(rides)}")

    checkins = generate_checkins(ride_scenarios, tour_riders, scenario, rng)
    print(f"  Check-ins      : {len(checkins)}")

    # Upload or dry run
    if args.dry_run:
        print("\n--- DRY RUN — no data uploaded ---")
        print("\n  Summary:")
        print(f"    Profiles     : {len(profiles)}")
        print(f"    Tour riders  : {len(tour_riders)}")
        print(f"    Rides        : {len(rides)}")
        print(f"    Check-ins    : {len(checkins)}")
        for ride in rides:
            rid = ride['rideId']
            status = ride['status']
            name = ride['name']
            ccount = sum(1 for c in checkins if c['rideId'] == rid)
            print(f"      {rid} ({name}, {status}): {ccount} check-ins")
        print()
    else:
        print("\nUploading to DynamoDB...")
        session = boto3.Session(region_name=args.region) if args.region else boto3.Session()
        total_failed = upload_data(
            session, args.stack_name, tour_id,
            profiles, tour_riders, rides, checkins,
        )

        print("\n=== Generation Complete ===")
        print(f"  Profiles   : {len(profiles)}")
        print(f"  Tour riders: {len(tour_riders)}")
        print(f"  Rides      : {len(rides)}")
        print(f"  Check-ins  : {len(checkins)}")
        if total_failed:
            print(f"  FAILED     : {total_failed}")
            sys.exit(1)
        print()


if __name__ == '__main__':
    main()
