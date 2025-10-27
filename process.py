#!/usr/bin/env python3
"""
ARIN IPv4 Waitlist Tracker

This script analyzes the ARIN IPv4 waitlist and estimates wait times based on historical
data of cleared blocks. It tracks changes over time using git history and provides
comprehensive statistics including request churn, age distribution, and flexibility metrics.

Key Features:
- Fetches current waitlist and historical cleared blocks data from ARIN
- Compares snapshots to track added/removed requests
- Calculates wait time estimates based on historical clearance rates
- Tracks request flexibility (willingness to accept different block sizes)
- Analyzes request age distribution across CIDR sizes
- Can reprocess entire git history to regenerate time-series data
"""

import pandas as pd  # For processing historical clearance data
import json  # For parsing ARIN waitlist JSON
from collections import Counter  # For counting CIDR sizes
import math  # For wait time calculations
import requests  # For fetching data from ARIN URLs
import io  # For in-memory CSV processing
import argparse  # For command-line argument parsing
import csv  # For CSV output
import sys  # For stderr output and exit codes
import os  # For file path operations
import subprocess  # For git commands in reprocessing mode
from datetime import datetime, timezone  # For timestamp handling and age calculations

# --- URLs for the data ---
# Historical data: CSV of all IPv4 blocks cleared from the waitlist
HISTORICAL_DATA_URL = 'https://www.arin.net/resources/guide/ipv4/blocks_cleared/waiting_list_blocks_issued.csv'
# Current waitlist: JSON API endpoint with all pending requests
CURRENT_WAITLIST_URL = 'https://accountws.arin.net/public/rest/waitingList'

def parse_arguments():
    """
    Parse command-line arguments for the waitlist tracker.

    Returns:
        argparse.Namespace: Parsed arguments containing:
            - csv: Output in CSV format (vs human-readable text)
            - no_header: Skip CSV header row (for appending to existing files)
            - file: Local JSON file path (instead of fetching from URL)
            - previous_file: Previous snapshot for comparison (enables add/remove tracking)
            - reprocess_history: Regenerate entire CSV from git history
            - output_csv: Output file path for reprocessing mode
    """
    parser = argparse.ArgumentParser(description='Analyze ARIN IPv4 waitlist and estimate wait times')
    parser.add_argument('--csv', action='store_true', help='Output data in CSV format')
    parser.add_argument('--no-header', action='store_true', help='Skip CSV header (useful for appending to existing files)')
    parser.add_argument('--file', type=str, help='Use local waitlist file (JSON format) instead of fetching from URL')
    parser.add_argument('--previous-file', type=str, help='Previous waitlist file to compare against for tracking adds/removes')
    parser.add_argument('--reprocess-history', action='store_true', help='Reprocess all git history commits and regenerate CSV')
    parser.add_argument('--output-csv', type=str, default='docs/waitlist_data.csv', help='Output CSV file path (default: docs/waitlist_data.csv)')
    return parser.parse_args()

def parse_waitlist_json(json_content):
    """
    Parse JSON waitlist data and normalize field names for consistency.

    ARIN's API format has changed over time (lowercase -> camelCase), so we normalize
    to the current camelCase format for consistent processing.

    Args:
        json_content (str): Raw JSON string from ARIN API or historical file

    Returns:
        tuple: (normalized_data, last_timestamp)
            - normalized_data: List of dicts with keys: waitListActionDate, minimumCidr, maximumCidr
            - last_timestamp: ISO format timestamp of the most recent request action
    """
    data_list = json.loads(json_content)

    # Normalize field names to match current API format
    normalized_data = []
    timestamps = []

    for item in data_list:
        # Handle both old format (lowercase) and new format (camelCase)
        # This ensures compatibility with historical data files
        timestamp = item.get('waitListActionDate') or item.get('waitlistactiondate')
        min_cidr = item.get('minimumCidr') or item.get('minimumcidr')
        max_cidr = item.get('maximumCidr') or item.get('maximumcidr')

        # Only include valid entries with required fields
        if timestamp and max_cidr:
            timestamps.append(timestamp)
            normalized_data.append({
                'waitListActionDate': timestamp,  # ISO format datetime when request was created
                'minimumCidr': int(min_cidr) if min_cidr else None,  # Smallest block they'll accept
                'maximumCidr': int(max_cidr)  # Largest block they'll accept (their preference)
            })

    # Find the most recent timestamp (used as snapshot timestamp)
    last_timestamp = max(timestamps) if timestamps else None

    return normalized_data, last_timestamp

def load_waitlist_data(file_path):
    """
    Load waitlist data from local JSON file.

    Args:
        file_path (str): Path to JSON file containing waitlist data

    Returns:
        tuple: (normalized_data, last_timestamp) from parse_waitlist_json()
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    return parse_waitlist_json(content)

def compare_waitlists(current_data, previous_data):
    """
    Compare current and previous waitlist snapshots to track request churn and flexibility.

    This function performs set-based comparison using waitListActionDate as a unique identifier
    to determine which requests were added or removed between snapshots. It also analyzes
    requester flexibility (willingness to accept different block sizes) and tracks changes
    in size preferences over time.

    Args:
        current_data (list): Current waitlist data (list of normalized request dicts)
        previous_data (list): Previous waitlist data for comparison (or None/empty for first run)

    Returns:
        tuple: (added_by_cidr, removed_by_cidr, added_count, removed_count,
                flexibility_stats, size_change_stats)
            - added_by_cidr: Counter of added requests by CIDR size {'22': count, '23': count, '24': count}
            - removed_by_cidr: Counter of removed requests by CIDR size
            - added_count: Total number of requests added since previous snapshot
            - removed_count: Total number of requests removed (fulfilled or cancelled)
            - flexibility_stats: Dict with flexibility metrics (see below)
            - size_change_stats: Dict tracking size requirement changes (see below)
    """
    # Create dictionaries keyed by waitListActionDate (unique identifier for each request)
    # This allows O(1) lookup and easy set operations to find differences
    current_requests = {item['waitListActionDate']: item for item in current_data}
    previous_requests = {item['waitListActionDate']: item for item in previous_data} if previous_data else {}

    # Find added and removed requests using set difference operations
    # Added: present in current but not in previous
    # Removed: present in previous but not in current (fulfilled or cancelled)
    added_ids = set(current_requests.keys()) - set(previous_requests.keys())
    removed_ids = set(previous_requests.keys()) - set(current_requests.keys())

    # Count added/removed requests by CIDR size (using maximumCidr as their preference)
    added_by_cidr = Counter()
    removed_by_cidr = Counter()

    for req_id in added_ids:
        cidr = current_requests[req_id]['maximumCidr']
        added_by_cidr[str(cidr)] += 1  # Convert to string for consistency with CSV output

    for req_id in removed_ids:
        cidr = previous_requests[req_id]['maximumCidr']
        removed_by_cidr[str(cidr)] += 1

    # Total counts across all CIDR sizes
    added_count = len(added_ids)
    removed_count = len(removed_ids)

    # === Flexibility Analysis ===
    # Track how many requesters are willing to accept different block sizes
    # Exact: minimumCidr == maximumCidr (only want one specific size)
    # Flexible: minimumCidr != maximumCidr (willing to accept a range)
    flexible_count = 0
    exact_count = 0
    total_flexibility = 0  # Sum of flexibility ranges for calculating average

    for item in current_data:
        min_cidr = item.get('minimumCidr')  # Smallest block they'll accept
        max_cidr = item.get('maximumCidr')  # Largest block they'll accept

        if min_cidr is not None and max_cidr is not None:
            if min_cidr == max_cidr:
                exact_count += 1  # Only want exactly this size
            else:
                flexible_count += 1  # Willing to accept a range

            # Calculate flexibility as the CIDR range
            # IMPORTANT: In CIDR notation, SMALLER numbers = LARGER networks
            # Example: minimumCidr=24 (/24 = 256 IPs), maximumCidr=22 (/22 = 1024 IPs)
            # This means "willing to accept /24, /23, or /22" (small to large)
            # Flexibility = abs(max - min) = number of CIDR levels they'll accept
            total_flexibility += abs(max_cidr - min_cidr)

    total_requests = len(current_data)
    avg_flexibility = total_flexibility / total_requests if total_requests > 0 else 0

    # === Size Change Tracking ===
    # For requests that exist in both snapshots, track if they changed their size requirements
    # This can indicate desperation (upsizing) or strategic adjustments (downsizing)
    size_changes = 0  # Total number of requests that changed their size requirements
    upsize_changes = 0  # Changed to want larger blocks (smaller CIDR number) - potentially more desperate
    downsize_changes = 0  # Changed to want smaller blocks (larger CIDR number) - potentially more strategic
    flexibility_changes = 0  # Changed from exact to flexible or vice versa

    # Find requests present in both snapshots using set intersection
    for req_id in set(current_requests.keys()) & set(previous_requests.keys()):
        curr = current_requests[req_id]
        prev = previous_requests[req_id]

        curr_min = curr.get('minimumCidr')
        curr_max = curr.get('maximumCidr')
        prev_min = prev.get('minimumCidr')
        prev_max = prev.get('maximumCidr')

        # Only process if all values are present
        if all(x is not None for x in [curr_min, curr_max, prev_min, prev_max]):
            # Check if anything changed
            if curr_min != prev_min or curr_max != prev_max:
                size_changes += 1

                # Check if maximum changed (what they're willing to accept as largest)
                # Remember: SMALLER CIDR number = LARGER network
                if curr_max < prev_max:  # Wants larger block now (e.g., /23 -> /22)
                    upsize_changes += 1
                elif curr_max > prev_max:  # Wants smaller block now (e.g., /22 -> /23)
                    downsize_changes += 1

                # Check if flexibility stance changed
                prev_flexible = (prev_min != prev_max)  # Was flexible
                curr_flexible = (curr_min != curr_max)  # Is flexible
                if prev_flexible != curr_flexible:
                    flexibility_changes += 1  # Switched between exact and flexible

    # Package flexibility statistics for return
    flexibility_stats = {
        'flexible_requests': flexible_count,  # Count of requests willing to accept range
        'exact_requests': exact_count,  # Count of requests wanting exact size only
        'avg_flexibility': avg_flexibility  # Average CIDR range across all requests
    }

    # Package size change statistics for return
    size_change_stats = {
        'size_changes': size_changes,  # Total requests that modified their size requirements
        'upsize_changes': upsize_changes,  # Requests that increased maximum block size (desperation?)
        'downsize_changes': downsize_changes,  # Requests that decreased maximum block size (strategic?)
        'flexibility_changes': flexibility_changes  # Requests that changed exact/flexible stance
    }

    return added_by_cidr, removed_by_cidr, added_count, removed_count, flexibility_stats, size_change_stats

def calculate_age_distribution(waitlist_data, reference_time=None):
    """
    Calculate age distribution of waitlist requests binned by time ranges and CIDR sizes.

    This function analyzes how long requests have been waiting by comparing their
    waitListActionDate (creation time) to a reference time (current time or historical
    snapshot time). Results are binned into age ranges and broken down by CIDR size
    for visualization purposes.

    Args:
        waitlist_data (list): List of normalized request dicts
        reference_time (str|datetime|None): Time to measure ages against
            - None: Use current time (for live analysis)
            - str: ISO format timestamp (for historical reprocessing)
            - datetime: Explicit datetime object

    Returns:
        dict: Age distribution with keys:
            - bins: Dict of total counts per age range {'0-3_months': count, ...}
            - bins_by_size: Nested dict of counts by age and CIDR {age: {cidr: count}}
            - avg_age_days: Mean age across all requests
            - median_age_days: Median age across all requests
            - min_age_days: Youngest request age
            - max_age_days: Oldest request age
    """
    # Normalize reference_time to timezone-aware datetime
    if reference_time is None:
        reference_time = datetime.now(timezone.utc)  # Current time for live analysis
    elif isinstance(reference_time, str):
        # Parse ISO format timestamp (e.g., from git commit or CSV)
        reference_time = datetime.fromisoformat(reference_time.replace('Z', '+00:00'))

    # Ensure reference_time is timezone-aware for consistent comparisons
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)

    # Initialize age bins for overall distribution
    age_bins = {
        '0-3_months': 0,      # Very recent requests
        '3-6_months': 0,      # Recent requests
        '6-12_months': 0,     # Moderate age requests
        '12-24_months': 0,    # Old requests
        '24+_months': 0       # Very old requests (potential concern)
    }

    # Initialize age bins broken down by CIDR size for stacked visualization
    # This allows us to see which block sizes dominate each age range
    age_bins_by_size = {
        '0-3_months': {'22': 0, '23': 0, '24': 0},
        '3-6_months': {'22': 0, '23': 0, '24': 0},
        '6-12_months': {'22': 0, '23': 0, '24': 0},
        '12-24_months': {'22': 0, '23': 0, '24': 0},
        '24+_months': {'22': 0, '23': 0, '24': 0}
    }

    ages_days = []  # Collect all ages for statistical calculations

    # Process each request to calculate its age
    for item in waitlist_data:
        action_date_str = item.get('waitListActionDate')
        if not action_date_str:
            continue  # Skip requests without creation date

        try:
            # Parse the ISO format action date
            action_date = datetime.fromisoformat(action_date_str.replace('Z', '+00:00'))

            # Calculate age in days (how long this request has been waiting)
            age_days = (reference_time - action_date).days
            ages_days.append(age_days)

            # Determine CIDR size for this request (use minimumCidr as identifier)
            min_cidr = item.get('minimumCidr')
            cidr_key = str(min_cidr) if min_cidr in [22, 23, 24] else None

            # Convert days to months using average days per month (365.25/12)
            age_months = age_days / 30.44

            # Bin the request by age range and optionally by CIDR size
            if age_months < 3:
                age_bins['0-3_months'] += 1
                if cidr_key:
                    age_bins_by_size['0-3_months'][cidr_key] += 1
            elif age_months < 6:
                age_bins['3-6_months'] += 1
                if cidr_key:
                    age_bins_by_size['3-6_months'][cidr_key] += 1
            elif age_months < 12:
                age_bins['6-12_months'] += 1
                if cidr_key:
                    age_bins_by_size['6-12_months'][cidr_key] += 1
            elif age_months < 24:
                age_bins['12-24_months'] += 1
                if cidr_key:
                    age_bins_by_size['12-24_months'][cidr_key] += 1
            else:
                age_bins['24+_months'] += 1
                if cidr_key:
                    age_bins_by_size['24+_months'][cidr_key] += 1

        except (ValueError, AttributeError) as e:
            # Skip malformed dates (shouldn't happen with normalized data)
            continue

    # Calculate summary statistics across all request ages
    avg_age_days = sum(ages_days) / len(ages_days) if ages_days else 0
    min_age_days = min(ages_days) if ages_days else 0
    max_age_days = max(ages_days) if ages_days else 0
    median_age_days = sorted(ages_days)[len(ages_days) // 2] if ages_days else 0

    return {
        'bins': age_bins,  # Total counts per age range
        'bins_by_size': age_bins_by_size,  # Counts by age range and CIDR size
        'avg_age_days': avg_age_days,  # Mean wait time
        'min_age_days': min_age_days,  # Shortest wait
        'max_age_days': max_age_days,  # Longest wait
        'median_age_days': median_age_days  # Median wait time
    }

def output_csv(total_requests, requests_22, requests_23, requests_24,
               avg_22_cleared, avg_23_cleared, avg_24_cleared,
               quarters_22, quarters_23, quarters_24, years_22, years_23, years_24,
               added_22=0, added_23=0, added_24=0, added_total=0,
               removed_22=0, removed_23=0, removed_24=0, removed_total=0,
               flexible_requests=0, exact_requests=0, avg_flexibility=0.0,
               size_changes=0, upsize_changes=0, downsize_changes=0, flexibility_changes=0,
               age_0_3mo=0, age_3_6mo=0, age_6_12mo=0, age_12_24mo=0, age_24plus=0,
               avg_age_days=0, median_age_days=0, min_age_days=0, max_age_days=0,
               age_0_3mo_22=0, age_0_3mo_23=0, age_0_3mo_24=0,
               age_3_6mo_22=0, age_3_6mo_23=0, age_3_6mo_24=0,
               age_6_12mo_22=0, age_6_12mo_23=0, age_6_12mo_24=0,
               age_12_24mo_22=0, age_12_24mo_23=0, age_12_24mo_24=0,
               age_24plus_22=0, age_24plus_23=0, age_24plus_24=0,
               include_header=True):
    """
    Output comprehensive waitlist statistics in CSV format for time-series analysis.

    This function outputs 54 columns of data covering:
    - Request counts by CIDR size
    - Request churn (added/removed)
    - Flexibility metrics
    - Age distribution (total and by CIDR size)
    - Wait time estimates based on historical clearance rates

    Args:
        All parameters are metrics calculated from waitlist analysis
        include_header (bool): Whether to output CSV header row

    Output:
        Writes one CSV row to stdout with timestamp and all metrics
    """
    writer = csv.writer(sys.stdout)

    # Header row (optional)
    if include_header:
        writer.writerow([
            'timestamp',
            'total_requests',
            'requests_22',
            'requests_23',
            'requests_24',
            'added_22',
            'added_23',
            'added_24',
            'added_total',
            'removed_22',
            'removed_23',
            'removed_24',
            'removed_total',
            'net_change',
            'flexible_requests',
            'exact_requests',
            'avg_flexibility',
            'age_0_3mo_22',
            'age_0_3mo_23',
            'age_0_3mo_24',
            'age_3_6mo_22',
            'age_3_6mo_23',
            'age_3_6mo_24',
            'age_6_12mo_22',
            'age_6_12mo_23',
            'age_6_12mo_24',
            'age_12_24mo_22',
            'age_12_24mo_23',
            'age_12_24mo_24',
            'age_24plus_22',
            'age_24plus_23',
            'age_24plus_24',
            'avg_22_cleared_per_quarter',
            'avg_23_cleared_per_quarter',
            'avg_24_cleared_per_quarter',
            'estimated_years_22',
            'estimated_years_23',
            'estimated_years_24'
        ])

    # Use the waitlist data timestamp if available (from global scope), otherwise current time
    # The global data_timestamp is set by main code after fetching/loading the waitlist
    timestamp = data_timestamp if 'data_timestamp' in globals() and data_timestamp else datetime.now().isoformat()

    # Calculate net change (positive = waitlist growing, negative = waitlist shrinking)
    net_change = added_total - removed_total

    # Data row - output all metrics in same order as header
    # Note: Some values are formatted to specific decimal places for consistency
    writer.writerow([
        timestamp,
        total_requests,
        requests_22,
        requests_23,
        requests_24,
        added_22,
        added_23,
        added_24,
        added_total,
        removed_22,
        removed_23,
        removed_24,
        removed_total,
        net_change,
        flexible_requests,
        exact_requests,
        f'{avg_flexibility:.2f}',
        age_0_3mo_22,
        age_0_3mo_23,
        age_0_3mo_24,
        age_3_6mo_22,
        age_3_6mo_23,
        age_3_6mo_24,
        age_6_12mo_22,
        age_6_12mo_23,
        age_6_12mo_24,
        age_12_24mo_22,
        age_12_24mo_23,
        age_12_24mo_24,
        age_24plus_22,
        age_24plus_23,
        age_24plus_24,
        f'{avg_22_cleared:.1f}',
        f'{avg_23_cleared:.1f}',
        f'{avg_24_cleared:.1f}',
        f'{years_22:.1f}' if years_22 != float('inf') else 'inf',
        f'{years_23:.1f}' if years_23 != float('inf') else 'inf',
        f'{years_24:.1f}' if years_24 != float('inf') else 'inf'
    ])

def output_text(total_requests, requests_22, requests_23, requests_24,
                avg_22_cleared, avg_23_cleared, avg_24_cleared,
                quarters_22, quarters_23, quarters_24, years_22, years_23, years_24,
                added_22=0, added_23=0, added_24=0, added_total=0,
                removed_22=0, removed_23=0, removed_24=0, removed_total=0):
    """
    Output waitlist summary in human-readable Markdown format.

    This is the default output mode (when --csv is not specified). It provides
    a narrative summary of the waitlist status, changes, and estimated wait times.

    Args:
        All parameters are metrics calculated from waitlist analysis

    Output:
        Prints formatted Markdown text to stdout
    """
    print("### Current Waitlist Summary ###")
    print(f"As of the most recent data, the waitlist has **{total_requests} requests**.")
    print("The requests are for the following network sizes:")
    print(f"* **/22:** {requests_22} requests")
    print(f"* **/23:** {requests_23} requests")
    print(f"* **/24:** {requests_24} requests")

    if added_total > 0 or removed_total > 0:
        print("\n" + "---")
        print("### Changes from Previous Snapshot ###")
        print(f"* **Added:** {added_total} requests (/22: {added_22}, /23: {added_23}, /24: {added_24})")
        print(f"* **Removed:** {removed_total} requests (/22: {removed_22}, /23: {removed_23}, /24: {removed_24})")
        print(f"* **Net Change:** {added_total - removed_total:+d} requests")

    print("\n" + "---")

    print("### Historical Analysis ###")
    print("Over the analyzed period, ARIN has cleared an average of:")
    print(f"* **{avg_22_cleared:.1f}** /22 blocks per quarter")
    print(f"* **{avg_23_cleared:.1f}** /23 blocks per quarter")
    print(f"* **{avg_24_cleared:.1f}** /24 blocks per quarter")
    print("\n" + "---")

    print("### Estimated Wait Time ###")
    print("Based on the current queue and historical rates, here are the estimated wait times:")
    print(f"* **For a /22 network:**")
    print(f"    * There are **{requests_22} requests** in the queue.")
    print(f"    * At a rate of **{avg_22_cleared:.1f} blocks cleared per quarter**, the estimated wait time is approximately **{quarters_22} quarters**, or **{years_22:.1f} years**.")
    print(f"* **For a /23 network:**")
    print(f"    * There are **{requests_23} requests** in the queue.")
    print(f"    * At a rate of **{avg_23_cleared:.1f} blocks cleared per quarter**, the estimated wait time is approximately **{quarters_23} quarters**, or **{years_23:.1f} years**.")
    print(f"* **For a /24 network:**")
    print(f"    * There are **{requests_24} requests** in the queue.")
    print(f"    * At a rate of **{avg_24_cleared:.1f} blocks cleared per quarter**, the estimated wait time is approximately **{quarters_24} quarters**, or **{years_24:.1f} years**.")

def get_git_commits_for_file(file_path):
    """
    Get all git commits that modified a specific file, in chronological order.

    This is used for reprocessing mode to find all historical snapshots of the waitlist.

    Args:
        file_path (str): Path to file to track (e.g., 'data/waitlist_data.json')

    Returns:
        list: List of commit hashes in chronological order (oldest first)
    """
    try:
        # Use git log with --reverse to get commits in chronological order (oldest first)
        # --format=%H outputs only the commit hash
        result = subprocess.run(
            ['git', 'log', '--format=%H', '--reverse', '--', file_path],
            capture_output=True,
            text=True,
            check=True
        )

        commits = result.stdout.strip().split('\n')
        return [c for c in commits if c]  # Filter out empty strings
    except subprocess.CalledProcessError as e:
        print(f"Error getting git commits: {e}", file=sys.stderr)
        return []

def get_file_at_commit(commit_hash, file_path):
    """
    Get the contents of a file at a specific git commit.

    Args:
        commit_hash (str): Git commit hash
        file_path (str): Path to file within the repository

    Returns:
        str: File contents at that commit, or None if file didn't exist
    """
    try:
        result = subprocess.run(
            ['git', 'show', f'{commit_hash}:{file_path}'],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return None  # File didn't exist at this commit

def get_commit_date(commit_hash):
    """
    Get the commit date in ISO format for a given commit hash.

    Args:
        commit_hash (str): Git commit hash

    Returns:
        str: ISO format timestamp of the commit, or None on error
    """
    try:
        result = subprocess.run(
            ['git', 'show', '-s', '--format=%cI', commit_hash],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None

def reprocess_git_history(output_file):
    """
    Reprocess entire git history to regenerate time-series CSV from all waitlist snapshots.

    This function walks through all git commits that modified data/waitlist_data.json,
    processes each snapshot to calculate metrics, and writes a complete CSV file with
    historical time-series data. This is useful for:
    - Regenerating CSV after adding new columns/metrics
    - Rebuilding data after git history changes (e.g., adding backdated commits)
    - Ensuring consistency across all historical data points

    Args:
        output_file (str): Path to output CSV file (e.g., 'docs/waitlist_data.csv')

    Process:
        1. Find all commits that modified waitlist_data.json (in chronological order)
        2. For each commit:
           - Extract waitlist JSON at that commit
           - Calculate all metrics (counts, churn, flexibility, age distribution)
           - Write CSV row with commit timestamp
        3. Result: Complete time-series CSV with one row per commit
    """
    print("Reprocessing git history...", file=sys.stderr)

    # Get all commits for waitlist_data.json in chronological order
    commits = get_git_commits_for_file('data/waitlist_data.json')

    if not commits:
        print("No commits found for data/waitlist_data.json", file=sys.stderr)
        return

    print(f"Found {len(commits)} commits to process", file=sys.stderr)

    # Create output directory if needed (e.g., 'docs/')
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    # Open output file
    with open(output_file, 'w', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)

        # Write header
        writer.writerow([
            'timestamp',
            'total_requests',
            'requests_22',
            'requests_23',
            'requests_24',
            'added_22',
            'added_23',
            'added_24',
            'added_total',
            'removed_22',
            'removed_23',
            'removed_24',
            'removed_total',
            'net_change',
            'flexible_requests',
            'exact_requests',
            'avg_flexibility',
            'age_0_3mo_22',
            'age_0_3mo_23',
            'age_0_3mo_24',
            'age_3_6mo_22',
            'age_3_6mo_23',
            'age_3_6mo_24',
            'age_6_12mo_22',
            'age_6_12mo_23',
            'age_6_12mo_24',
            'age_12_24mo_22',
            'age_12_24mo_23',
            'age_12_24mo_24',
            'age_24plus_22',
            'age_24plus_23',
            'age_24plus_24',
            'avg_22_cleared_per_quarter',
            'avg_23_cleared_per_quarter',
            'avg_24_cleared_per_quarter',
            'estimated_years_22',
            'estimated_years_23',
            'estimated_years_24'
        ])

        # Track previous snapshot for calculating churn (added/removed requests)
        previous_data = None

        # === Main Processing Loop ===
        # Process each commit in chronological order to build time-series data
        for i, commit in enumerate(commits):
            print(f"Processing commit {i+1}/{len(commits)}: {commit[:8]}", file=sys.stderr)

            # Extract waitlist_data.json content at this specific commit
            content = get_file_at_commit(commit, 'data/waitlist_data.json')
            if not content:
                print(f"  Could not get file at commit {commit[:8]}, skipping", file=sys.stderr)
                continue

            # Get the commit timestamp (used as snapshot timestamp)
            commit_date = get_commit_date(commit)
            if not commit_date:
                print(f"  Could not get date for commit {commit[:8]}, skipping", file=sys.stderr)
                continue

            # Parse the JSON waitlist data from this commit
            try:
                waitlist_data, _ = parse_waitlist_json(content)
            except Exception as e:
                print(f"  Error parsing JSON at commit {commit[:8]}: {e}", file=sys.stderr)
                continue

            # === Calculate Metrics ===

            # Compare with previous snapshot to calculate request churn
            added_by_cidr, removed_by_cidr, added_total, removed_total, flexibility_stats, size_change_stats = compare_waitlists(waitlist_data, previous_data)

            # Count total requests and requests by CIDR size
            requests_list = [str(item['maximumCidr']) for item in waitlist_data if 'maximumCidr' in item]
            waitlist_counts = Counter(requests_list)

            requests_22 = waitlist_counts.get('22', 0)
            requests_23 = waitlist_counts.get('23', 0)
            requests_24 = waitlist_counts.get('24', 0)
            total_requests = len(waitlist_data)

            # Extract added counts by CIDR size
            added_22 = added_by_cidr.get('22', 0)
            added_23 = added_by_cidr.get('23', 0)
            added_24 = added_by_cidr.get('24', 0)

            # Extract removed counts by CIDR size
            removed_22 = removed_by_cidr.get('22', 0)
            removed_23 = removed_by_cidr.get('23', 0)
            removed_24 = removed_by_cidr.get('24', 0)

            # === Historical Clearance Rate Analysis ===
            # Fetch historical data to calculate wait time estimates
            # NOTE: We fetch this for every commit (could be optimized to fetch once)
            try:
                # Fetch the historical cleared blocks CSV from ARIN
                response = requests.get(HISTORICAL_DATA_URL, timeout=10)
                response.raise_for_status()

                csv_file = io.StringIO(response.text)
                historical_df = pd.read_csv(csv_file)
                # Clean column names (remove whitespace)
                historical_df.columns = historical_df.columns.str.strip()
                # Extract CIDR size from 'CIDR Prefix' column (e.g., '192.0.2.0/24' -> 24)
                historical_df['Prefix Size'] = historical_df['CIDR Prefix'].apply(lambda x: int(x.split('/')[1]))
                # Parse dates in ARIN's format (MM/DD/YY)
                historical_df['Date Reissued'] = pd.to_datetime(historical_df['Date Reissued'], format='%m/%d/%y')

                # === Critical: Apply timestamp cutoff ===
                # Only include cleared blocks BEFORE this commit's timestamp
                # This ensures historical accuracy - we only count blocks that had been cleared by that point in time
                cutoff_date = pd.to_datetime(commit_date).tz_localize(None)
                historical_df = historical_df[historical_df['Date Reissued'] <= cutoff_date]

                # Calculate average clearance rates per quarter by CIDR size
                quarterly_counts = historical_df.groupby([pd.Grouper(key='Date Reissued', freq='QE'), 'Prefix Size']).size().unstack(fill_value=0)
                avg_cleared_per_quarter = quarterly_counts.mean()
                avg_22_cleared = avg_cleared_per_quarter.get(22, 0)
                avg_23_cleared = avg_cleared_per_quarter.get(23, 0)
                avg_24_cleared = avg_cleared_per_quarter.get(24, 0)

            except Exception as e:
                print(f"  Error fetching historical data: {e}", file=sys.stderr)
                # Fallback to zero if historical data unavailable
                avg_22_cleared = avg_23_cleared = avg_24_cleared = 0

            # Calculate estimated wait times based on queue size and clearance rate
            # Use ceil() because partial quarters still mean waiting for the full quarter
            quarters_22 = math.ceil(requests_22 / avg_22_cleared) if avg_22_cleared > 0 else float('inf')
            quarters_23 = math.ceil(requests_23 / avg_23_cleared) if avg_23_cleared > 0 else float('inf')
            quarters_24 = math.ceil(requests_24 / avg_24_cleared) if avg_24_cleared > 0 else float('inf')

            # Convert quarters to years for easier interpretation
            years_22 = quarters_22 / 4
            years_23 = quarters_23 / 4
            years_24 = quarters_24 / 4

            # Calculate age distribution using commit date as reference time
            # This gives us historically accurate ages (how old requests were at this snapshot)
            age_dist = calculate_age_distribution(waitlist_data, commit_date)

            # === Write CSV Row ===
            # Write all calculated metrics for this commit as one CSV row
            net_change = added_total - removed_total
            writer.writerow([
                commit_date,
                total_requests,
                requests_22,
                requests_23,
                requests_24,
                added_22,
                added_23,
                added_24,
                added_total,
                removed_22,
                removed_23,
                removed_24,
                removed_total,
                net_change,
                flexibility_stats['flexible_requests'],
                flexibility_stats['exact_requests'],
                f"{flexibility_stats['avg_flexibility']:.2f}",
                age_dist['bins_by_size']['0-3_months']['22'],
                age_dist['bins_by_size']['0-3_months']['23'],
                age_dist['bins_by_size']['0-3_months']['24'],
                age_dist['bins_by_size']['3-6_months']['22'],
                age_dist['bins_by_size']['3-6_months']['23'],
                age_dist['bins_by_size']['3-6_months']['24'],
                age_dist['bins_by_size']['6-12_months']['22'],
                age_dist['bins_by_size']['6-12_months']['23'],
                age_dist['bins_by_size']['6-12_months']['24'],
                age_dist['bins_by_size']['12-24_months']['22'],
                age_dist['bins_by_size']['12-24_months']['23'],
                age_dist['bins_by_size']['12-24_months']['24'],
                age_dist['bins_by_size']['24+_months']['22'],
                age_dist['bins_by_size']['24+_months']['23'],
                age_dist['bins_by_size']['24+_months']['24'],
                f'{avg_22_cleared:.1f}',
                f'{avg_23_cleared:.1f}',
                f'{avg_24_cleared:.1f}',
                f'{years_22:.1f}' if years_22 != float('inf') else 'inf',
                f'{years_23:.1f}' if years_23 != float('inf') else 'inf',
                f'{years_24:.1f}' if years_24 != float('inf') else 'inf'
            ])

            # Store this snapshot as "previous" for the next iteration
            # This enables churn calculation between consecutive commits
            previous_data = waitlist_data

    print(f"Reprocessing complete! Output written to {output_file}", file=sys.stderr)

# ============================================================================
# === MAIN EXECUTION STARTS HERE ===
# ============================================================================

# Parse command line arguments
args = parse_arguments()

# === Handle Reprocessing Mode ===
# If --reprocess-history flag is provided, regenerate entire CSV from git history and exit
if args.reprocess_history:
    reprocess_git_history(args.output_csv)
    sys.exit(0)

# === Normal Execution Mode ===
# Process current waitlist snapshot and optionally compare with previous snapshot

# Create data directory if it doesn't exist (for caching files)
os.makedirs('data', exist_ok=True)

# --- Step 1: Fetch and Analyze Historical Cleared Blocks Data ---
# This data is used to calculate average clearance rates and estimate wait times

try:
    # Fetch the historical cleared blocks CSV from ARIN
    # This contains all IPv4 blocks that have been issued from the waitlist
    response = requests.get(HISTORICAL_DATA_URL, timeout=10)
    response.raise_for_status()  # Raise exception for HTTP errors (4xx or 5xx)

    # Save a local copy of the historical data for reference
    with open('data/historical_data.csv', 'w', encoding='utf-8') as f:
        f.write(response.text)

    # Parse CSV into pandas DataFrame for analysis
    csv_file = io.StringIO(response.text)
    historical_df = pd.read_csv(csv_file)

    # Clean up column names (remove leading/trailing whitespace)
    historical_df.columns = historical_df.columns.str.strip()

    # Extract CIDR size from the 'CIDR Prefix' column
    # Example: '192.0.2.0/24' -> 24
    historical_df['Prefix Size'] = historical_df['CIDR Prefix'].apply(lambda x: int(x.split('/')[1]))

    # Convert 'Date Reissued' string to datetime objects for time-series analysis
    # ARIN uses MM/DD/YY format
    historical_df['Date Reissued'] = pd.to_datetime(historical_df['Date Reissued'], format='%m/%d/%y')

    # Note: historical_df will be filtered by timestamp cutoff later (after we get waitlist timestamp)

except requests.exceptions.RequestException as e:
    print(f"Error fetching historical data CSV: {e}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"An error occurred while processing historical data: {e}", file=sys.stderr)
    sys.exit(1)

# --- Step 2: Fetch and Analyze Current Waitlist ---
# Load current waitlist data either from URL (live) or local file (historical/testing)

try:
    if args.file:
        # === Local File Mode ===
        # Load waitlist from local JSON file (for historical analysis or testing)
        waitlist_data, data_timestamp = load_waitlist_data(args.file)

        # Save a standardized copy to data/waitlist_data.json
        with open('data/waitlist_data.json', 'w', encoding='utf-8') as f:
            json.dump(waitlist_data, f, indent=2)
    else:
        # === Live URL Mode (default) ===
        # Fetch the current waitlist JSON from ARIN's public API
        response = requests.get(CURRENT_WAITLIST_URL, timeout=10)
        response.raise_for_status()  # Raise exception for HTTP errors

        # Save the fetched data to local file for tracking in git
        with open('data/waitlist_data.json', 'w', encoding='utf-8') as f:
            json.dump(json.loads(response.text), f, indent=2)

        # Parse the JSON to extract normalized data and timestamp
        waitlist_data, data_timestamp = parse_waitlist_json(response.text)

    # === Load Previous Snapshot (if provided) ===
    # This enables churn tracking (added/removed requests)
    previous_data = None
    if args.previous_file:
        previous_data, _ = load_waitlist_data(args.previous_file)

    # === Calculate Metrics ===

    # Compare current vs previous to calculate churn and flexibility metrics
    added_by_cidr, removed_by_cidr, added_total, removed_total, flexibility_stats, size_change_stats = compare_waitlists(waitlist_data, previous_data)

    # Count requests by CIDR size (using maximumCidr as their preference)
    requests_list = [str(item['maximumCidr']) for item in waitlist_data if 'maximumCidr' in item]
    waitlist_counts = Counter(requests_list)

    requests_22 = waitlist_counts.get('22', 0)
    requests_23 = waitlist_counts.get('23', 0)
    requests_24 = waitlist_counts.get('24', 0)
    total_requests = len(waitlist_data)

    # Extract added counts by CIDR size
    added_22 = added_by_cidr.get('22', 0)
    added_23 = added_by_cidr.get('23', 0)
    added_24 = added_by_cidr.get('24', 0)

    # Extract removed counts by CIDR size
    removed_22 = removed_by_cidr.get('22', 0)
    removed_23 = removed_by_cidr.get('23', 0)
    removed_24 = removed_by_cidr.get('24', 0)

    # Calculate age distribution (how long requests have been waiting)
    age_dist = calculate_age_distribution(waitlist_data, data_timestamp)

except requests.exceptions.RequestException as e:
    print(f"Error fetching waitlist JSON: {e}", file=sys.stderr)
    sys.exit(1)
except json.JSONDecodeError as e:
    print(f"Error parsing waitlist JSON: {e}", file=sys.stderr)
    sys.exit(1)
except FileNotFoundError as e:
    print(f"Error: File not found: {e}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"An error occurred while processing the waitlist: {e}", file=sys.stderr)
    sys.exit(1)

# --- Step 3: Calculate Historical Clearance Rates ---
# Process the historical cleared blocks data to calculate average clearance rates

# === Apply Timestamp Cutoff (for historical accuracy) ===
# When processing historical snapshots, only count blocks cleared BEFORE the snapshot time
if args.file and data_timestamp:
    # Convert waitlist timestamp to pandas datetime (remove timezone for comparison)
    cutoff_date = pd.to_datetime(data_timestamp).tz_localize(None)
    print(f"Using timestamp cutoff: {cutoff_date}", file=sys.stderr)

    # Filter historical data to only include blocks cleared before the snapshot
    # This ensures wait time estimates are accurate for that point in time
    historical_df = historical_df[historical_df['Date Reissued'] <= cutoff_date]

# Group cleared blocks by quarter and CIDR size, then count occurrences
# This creates a time-series of clearance counts by size
quarterly_counts = historical_df.groupby([pd.Grouper(key='Date Reissued', freq='QE'), 'Prefix Size']).size().unstack(fill_value=0)

# Calculate average number of blocks cleared per quarter for each size
# This is the historical clearance rate used for wait time estimation
avg_cleared_per_quarter = quarterly_counts.mean()
avg_22_cleared = avg_cleared_per_quarter.get(22, 0)
avg_23_cleared = avg_cleared_per_quarter.get(23, 0)
avg_24_cleared = avg_cleared_per_quarter.get(24, 0)

# --- Step 4: Calculate Estimated Wait Times ---
# Estimate how long current requests will wait based on queue size and clearance rate

# Calculate estimated quarters to clear the entire queue for each size
# Formula: queue_size / clearance_rate
# Use ceil() because partial quarters round up to full waiting periods
quarters_22 = math.ceil(requests_22 / avg_22_cleared) if avg_22_cleared > 0 else float('inf')
quarters_23 = math.ceil(requests_23 / avg_23_cleared) if avg_23_cleared > 0 else float('inf')
quarters_24 = math.ceil(requests_24 / avg_24_cleared) if avg_24_cleared > 0 else float('inf')

# Convert quarters to years for easier interpretation (4 quarters = 1 year)
years_22 = quarters_22 / 4
years_23 = quarters_23 / 4
years_24 = quarters_24 / 4


# --- Step 5: Output Results ---
# Output all calculated metrics in the requested format (CSV or human-readable text)

# Choose output format based on --csv flag
if args.csv:
    # === CSV Output Mode ===
    # Output one row of time-series data for appending to tracking CSV
    output_csv(total_requests, requests_22, requests_23, requests_24,
               avg_22_cleared, avg_23_cleared, avg_24_cleared,
               quarters_22, quarters_23, quarters_24, years_22, years_23, years_24,
               added_22, added_23, added_24, added_total,
               removed_22, removed_23, removed_24, removed_total,
               flexibility_stats['flexible_requests'],
               flexibility_stats['exact_requests'],
               flexibility_stats['avg_flexibility'],
               size_change_stats['size_changes'],
               size_change_stats['upsize_changes'],
               size_change_stats['downsize_changes'],
               size_change_stats['flexibility_changes'],
               age_dist['bins']['0-3_months'],
               age_dist['bins']['3-6_months'],
               age_dist['bins']['6-12_months'],
               age_dist['bins']['12-24_months'],
               age_dist['bins']['24+_months'],
               age_dist['avg_age_days'],
               age_dist['median_age_days'],
               age_dist['min_age_days'],
               age_dist['max_age_days'],
               age_dist['bins_by_size']['0-3_months']['22'],
               age_dist['bins_by_size']['0-3_months']['23'],
               age_dist['bins_by_size']['0-3_months']['24'],
               age_dist['bins_by_size']['3-6_months']['22'],
               age_dist['bins_by_size']['3-6_months']['23'],
               age_dist['bins_by_size']['3-6_months']['24'],
               age_dist['bins_by_size']['6-12_months']['22'],
               age_dist['bins_by_size']['6-12_months']['23'],
               age_dist['bins_by_size']['6-12_months']['24'],
               age_dist['bins_by_size']['12-24_months']['22'],
               age_dist['bins_by_size']['12-24_months']['23'],
               age_dist['bins_by_size']['12-24_months']['24'],
               age_dist['bins_by_size']['24+_months']['22'],
               age_dist['bins_by_size']['24+_months']['23'],
               age_dist['bins_by_size']['24+_months']['24'],
               include_header=not args.no_header)
else:
    # === Human-Readable Text Output Mode (default) ===
    # Output formatted Markdown summary for human consumption
    output_text(total_requests, requests_22, requests_23, requests_24,
                avg_22_cleared, avg_23_cleared, avg_24_cleared,
                quarters_22, quarters_23, quarters_24, years_22, years_23, years_24,
                added_22, added_23, added_24, added_total,
                removed_22, removed_23, removed_24, removed_total)
