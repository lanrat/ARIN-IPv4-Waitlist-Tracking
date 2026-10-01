#!/usr/bin/env python3
"""
ARIN IPv4 Waitlist Tracker

This script analyzes the ARIN IPv4 waitlist and estimates wait times based on historical
data of issued blocks. It tracks changes over time using git history and provides
comprehensive statistics including request churn, age distribution, and flexibility metrics.

How wait times are estimated:
- The waitlist is a single first-come-first-served line (ordered by waitListActionDate)
  that ARIN fills in roughly quarterly batches. Per NRPM 4.1.8.2, requests are filled
  "subject to the size of each available address block" and never partially, so a /22
  needs a block that can hold a /22, while several /24 blocks cannot be combined.
- ARIN's issued-blocks list includes large blocks (/15-/21) that are split to fill many
  /22-/24 requests, so supply is the actual blocks issued, not a count of /22-/24 rows.
- Estimated wait for a new request of each size: the last 8 quarters of issued blocks are
  replayed as future batches over the current line (simulating how ARIN fills it, block by
  block), starting from each quarter in turn, and the time until the new request at the
  back of the line is filled is averaged.
- As a check against reality, each issuance batch is detected from snapshot diffs and the
  wait of the most recently joined request that was filled is recorded per block size.

Key Features:
- Fetches current waitlist and historical issued blocks data from ARIN
- Compares snapshots to track added/removed requests
- Estimates wait times per block size by simulating future batches
- Measures how long the most recently filled requests actually waited
- Tracks request flexibility (willingness to accept different block sizes)
- Analyzes request age distribution across CIDR sizes
- Can reprocess entire git history to regenerate time-series data
"""

import pandas as pd  # For processing historical issued blocks data
import json  # For parsing ARIN waitlist JSON
from collections import Counter  # For counting CIDR sizes
import requests  # For fetching data from ARIN URLs
import io  # For in-memory CSV processing
import argparse  # For command-line argument parsing
import csv  # For CSV output
import sys  # For stderr output and exit codes
import os  # For file path operations
import subprocess  # For git commands in reprocessing mode
from datetime import datetime, timedelta, timezone  # For timestamp handling and age calculations
from zoneinfo import ZoneInfo  # For repairing old US/Eastern timestamps

# --- URLs for the data ---
# Historical data: CSV of all IPv4 blocks issued to the waitlist
HISTORICAL_DATA_URL = 'https://www.arin.net/resources/guide/ipv4/blocks_cleared/waiting_list_blocks_issued.csv'
# Current waitlist: JSON API endpoint with all pending requests
CURRENT_WAITLIST_URL = 'https://accountws.arin.net/public/rest/waitingList'

# --- Wait time model parameters ---
# Recent quarters of issued blocks replayed as future batches (ARIN issues about one batch
# per quarter, and batch sizes vary by almost 10x, so a short window swings wildly)
SUPPLY_WINDOW_QUARTERS = 8
# Stop simulating future batches after this many (10 years); the wait is then reported as inf
MAX_SIMULATED_BATCHES = 40
DAYS_PER_QUARTER = 365.25 / 4
DAYS_PER_MONTH = 365.25 / 12
# A snapshot diff with at least this many removals is treated as an issuance batch.
# Between batches only a handful of requests are withdrawn per snapshot.
BATCH_MIN_REMOVALS = 10
# A request counts as "served" by a batch when at least SERVED_WINDOW_SHARE of the
# SERVED_WINDOW same-size requests up to and including it in line were removed. A local
# window ignores requests stuck at the front of the line and lone withdrawals further back.
SERVED_WINDOW = 10
SERVED_WINDOW_SHARE = 0.8
# Block sizes that can be requested from the waitlist
SIZES = (22, 23, 24)

# Old snapshots converted from ARIN's HTML page carry a bogus local mean time offset
# (-04:56) on what were US/Eastern wall-clock times
EASTERN = ZoneInfo('America/New_York')

# Columns of the time-series CSV (docs/waitlist_data.csv), in output order
CSV_HEADER = [
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
    'queue_24eq',  # /24 equivalents waiting (by maximumCidr)
    'supply_24eq_per_quarter',  # Average /24 equivalents issued per quarter (trailing window)
    'estimated_wait_months_22',  # Estimated wait for a new /22 request joining at this snapshot
    'estimated_wait_months_23',
    'estimated_wait_months_24',
    'last_fill_date_22',  # Date of the most recent batch that filled /22 requests
    'last_fill_date_23',
    'last_fill_date_24',
    'last_fill_wait_months_22',  # How long the newest filled /22 request had waited
    'last_fill_wait_months_23',
    'last_fill_wait_months_24'
]

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
            - output_csv: Time-series CSV path (read for the previous row in live mode,
              written in reprocessing mode)
    """
    parser = argparse.ArgumentParser(description='Analyze ARIN IPv4 waitlist and estimate wait times')
    parser.add_argument('--csv', action='store_true', help='Output data in CSV format')
    parser.add_argument('--no-header', action='store_true', help='Skip CSV header (useful for appending to existing files)')
    parser.add_argument('--file', type=str, help='Use local waitlist file (JSON format) instead of fetching from URL')
    parser.add_argument('--previous-file', type=str, help='Previous waitlist file to compare against for tracking adds/removes')
    parser.add_argument('--reprocess-history', action='store_true', help='Reprocess all git history commits and regenerate CSV')
    parser.add_argument('--output-csv', type=str, default='docs/waitlist_data.csv', help='Time-series CSV file path (default: docs/waitlist_data.csv)')
    return parser.parse_args()

def parse_timestamp(timestamp):
    """
    Parse an ARIN waitListActionDate (or snapshot timestamp) into a UTC datetime.

    ARIN's timestamp format has changed over time ('...+00:00' vs '...Z', with and
    without milliseconds), and old HTML-derived snapshots use a -04:56 offset that
    really means US/Eastern local time.

    Args:
        timestamp (str): ISO format timestamp

    Returns:
        datetime: Timezone-aware UTC datetime
    """
    if timestamp.endswith('-04:56'):
        local_time = datetime.fromisoformat(timestamp[:-6]).replace(tzinfo=EASTERN)
        return local_time.astimezone(timezone.utc)

    parsed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def format_timestamp(timestamp):
    """
    Format a datetime as a canonical UTC ISO string (e.g. '2026-10-01T08:08:44.000Z').

    Canonical strings sort chronologically and compare equal across ARIN format changes.
    """
    return timestamp.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

def request_key(item):
    """
    Unique identifier for a waitlist request: its waitListActionDate to the second.

    The date is kept when a request changes size, so it identifies a request across
    snapshots. Seconds precision is used because old snapshots lack milliseconds.
    """
    return item['waitListActionDate'][:19]

def to_naive_utc(timestamp):
    """Convert a timezone-aware datetime to naive UTC for comparison with pandas dates."""
    return timestamp.astimezone(timezone.utc).replace(tzinfo=None)

def parse_waitlist_json(json_content):
    """
    Parse JSON waitlist data and normalize field names and timestamps for consistency.

    ARIN's API format has changed over time (lowercase -> camelCase, timestamp formats),
    so we normalize to camelCase fields and canonical UTC timestamps.

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
            timestamp = format_timestamp(parse_timestamp(timestamp))
            timestamps.append(timestamp)
            normalized_data.append({
                'waitListActionDate': timestamp,  # Canonical UTC datetime when request joined the list
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

def fetch_issued_blocks():
    """
    Fetch ARIN's CSV of all IPv4 blocks issued to the waitlist.

    Returns:
        str: CSV text (without byte order mark)
    """
    response = requests.get(HISTORICAL_DATA_URL, timeout=10)
    response.raise_for_status()  # Raise exception for HTTP errors (4xx or 5xx)
    return response.text.lstrip('﻿')

def parse_issued_blocks(csv_text):
    """
    Parse ARIN's issued blocks CSV into a DataFrame.

    Args:
        csv_text (str): CSV text with 'CIDR Prefix' and 'Date Reissued' columns

    Returns:
        DataFrame: One row per issued block with added columns:
            - Prefix Size: CIDR prefix length (e.g., 24)
            - Size 24eq: Address space in /24 equivalents (/22 = 4, /16 = 256)
    """
    issued_df = pd.read_csv(io.StringIO(csv_text))

    # Clean up column names (remove whitespace and any byte order mark)
    issued_df.columns = issued_df.columns.str.strip().str.lstrip('﻿')

    # Extract CIDR size from the 'CIDR Prefix' column
    # Example: '192.0.2.0/24' -> 24
    issued_df['Prefix Size'] = issued_df['CIDR Prefix'].apply(lambda x: int(x.split('/')[1]))

    # Convert 'Date Reissued' string to datetime objects for time-series analysis
    # ARIN uses MM/DD/YY format
    issued_df['Date Reissued'] = pd.to_datetime(issued_df['Date Reissued'], format='%m/%d/%y')

    # Large blocks (/15-/21) are split to fill many /22-/24 requests, so supply is
    # measured in address space rather than block counts
    issued_df['Size 24eq'] = 2 ** (24 - issued_df['Prefix Size'])

    return issued_df

def calculate_queue_24eq(waitlist_data):
    """
    Total address space waiting, in /24 equivalents (using each request's maximumCidr).
    """
    return sum(2 ** (24 - item['maximumCidr']) for item in waitlist_data)

def recent_quarter_batches(issued_df, as_of):
    """
    Blocks issued in each of the last SUPPLY_WINDOW_QUARTERS calendar quarters, oldest first.

    The window ends with the current quarter once its batch has been issued, otherwise
    with the previous quarter. Quarters with no issuance are included as empty batches.
    Only blocks issued on or before as_of are used, so historical snapshots see only what
    had been issued at that time.

    Args:
        issued_df (DataFrame): Parsed issued blocks from parse_issued_blocks()
        as_of (datetime): Snapshot time

    Returns:
        list: One list of block prefix lengths per quarter (e.g. [[24, 24, 20], [], ...])
    """
    issued = issued_df[issued_df['Date Reissued'] <= to_naive_utc(as_of)]
    quarters = issued['Date Reissued'].dt.year * 4 + (issued['Date Reissued'].dt.month - 1) // 3

    current_quarter = as_of.year * 4 + (as_of.month - 1) // 3
    last_quarter = current_quarter if (quarters == current_quarter).any() else current_quarter - 1

    return [issued.loc[quarters == quarter, 'Prefix Size'].tolist()
            for quarter in range(last_quarter - SUPPLY_WINDOW_QUARTERS + 1, last_quarter + 1)]

def calculate_supply_rate(batches):
    """
    Average address space issued per quarter, in /24 equivalents.

    Args:
        batches (list): Per-quarter block prefix lengths from recent_quarter_batches()

    Returns:
        float: /24 equivalents issued per quarter
    """
    return sum(2 ** (24 - prefix) for blocks in batches for prefix in blocks) / len(batches)

def take_block(pool, size):
    """
    Take space for one /size request from a pool of free blocks.

    Uses the smallest free block that can hold it; splitting a larger block leaves the
    unused halves in the pool (e.g. a /22 from a /20 leaves a /21 and a /22).

    Args:
        pool (Counter): Free blocks as {prefix length: count}, modified in place
        size (int): Prefix length needed

    Returns:
        bool: True if a block was found
    """
    candidates = [prefix for prefix in pool if prefix <= size]
    if not candidates:
        return False

    prefix = max(candidates)  # Longest prefix = smallest block that fits
    pool[prefix] -= 1
    if pool[prefix] == 0:
        del pool[prefix]
    for split in range(prefix + 1, size + 1):
        pool[split] += 1
    return True

def allocate_blocks(queue, blocks):
    """
    Simulate one issuance batch: fill requests in line order from the blocks issued.

    Follows NRPM 4.1.8.2: requests are filled first-approved first, subject to the size of
    each available block, and never partially. Each request gets the largest size it
    accepts that a free block can hold. Requests no free block fits are skipped and keep
    their place in line. Checked against the 2025-2026 batches, this reproduces 85-99% of
    the requests ARIN actually filled.

    Args:
        queue (list): Requests in line order (normalized dicts)
        blocks (list): Prefix lengths of the blocks issued in the batch

    Returns:
        tuple: (filled, pool)
            - filled: Set of request keys that were filled
            - pool: Counter of blocks left over after the whole line was considered
    """
    pool = Counter(blocks)
    filled = set()

    for item in queue:
        if not pool:
            break  # Nothing left to issue

        # Try the largest acceptable size first (smaller CIDR number = larger block)
        for size in range(item['maximumCidr'], (item['minimumCidr'] or item['maximumCidr']) + 1):
            if take_block(pool, size):
                filled.add(request_key(item))
                break

    return filled, pool

def estimate_waits_by_size(waitlist_data, batches, snapshot_time, last_batch_time):
    """
    Estimate how long a new request of each size would wait, by simulating future batches.

    Future batches are assumed to look like the recent past: the recent quarters of issued
    blocks are replayed in order over the current line, starting from each quarter in turn,
    and the results are averaged. A new request joins at the back of the line, so it is
    filled in the first batch that has a suitable block left after everyone ahead of it
    has been considered (requests that join later are behind it and don't matter).

    Args:
        waitlist_data (list): Current waitlist snapshot (normalized)
        batches (list): Per-quarter block prefix lengths from recent_quarter_batches()
        snapshot_time (datetime): When the snapshot was taken
        last_batch_time (datetime): When the most recent batch was issued, or None

    Returns:
        dict: Estimated months of waiting by size {22: 11.2, 23: 11.0, 24: 7.5}
            (inf if not filled within MAX_SIMULATED_BATCHES)
    """
    queue = sorted(waitlist_data, key=lambda item: item['waitListActionDate'])

    # Batches arrive about once a quarter: the next is due a quarter after the last one
    # (or right away if that is already past)
    next_batch_time = snapshot_time
    if last_batch_time is not None:
        next_batch_time = max(last_batch_time + timedelta(days=DAYS_PER_QUARTER), snapshot_time)

    waits = {size: [] for size in SIZES}
    for start in range(len(batches)):
        remaining = queue
        pending = set(SIZES)

        for batch_number in range(MAX_SIMULATED_BATCHES):
            filled, pool = allocate_blocks(remaining, batches[(start + batch_number) % len(batches)])
            remaining = [item for item in remaining if request_key(item) not in filled]

            # A new request of this size is filled if a block that fits is left over
            for size in sorted(pending):
                if any(prefix <= size for prefix in pool):
                    fill_time = next_batch_time + timedelta(days=batch_number * DAYS_PER_QUARTER)
                    waits[size].append((fill_time - snapshot_time).total_seconds() / 86400 / DAYS_PER_MONTH)
                    pending.discard(size)

            if not pending:
                break

        for size in pending:
            waits[size].append(float('inf'))

    return {size: sum(months) / len(months) for size, months in waits.items()}

def detect_filled_requests(current_data, previous_data, snapshot_time, previous_time, issued_df):
    """
    Detect an issuance batch between two snapshots and measure how long filled requests waited.

    ARIN fills the waitlist in order of waitListActionDate, so a batch removes a run of
    the oldest requests. For each block size this finds the newest request that was
    served (most of the same-size requests just ahead of it were removed too) and
    reports how long it had waited.

    Args:
        current_data (list): Current waitlist snapshot (normalized)
        previous_data (list): Previous waitlist snapshot (normalized), or None
        snapshot_time (datetime): Time of the current snapshot
        previous_time (datetime): Time of the previous snapshot, or None if unknown
        issued_df (DataFrame): Parsed issued blocks, used to date the batch

    Returns:
        tuple: (fill_time, waits)
            - fill_time: When the batch was issued (ARIN's batch date when published,
              otherwise the snapshot time), or None if no batch was detected
            - waits: Dict of months waited by the newest served request {22: 10.0, ...};
              sizes with no served requests are omitted
    """
    if not previous_data:
        return None, {}

    current_keys = {request_key(item) for item in current_data}
    removed_keys = {request_key(item) for item in previous_data} - current_keys

    # A few removals between batches are withdrawals, not fills
    if len(removed_keys) < BATCH_MIN_REMOVALS:
        return None, {}

    # Use ARIN's batch date when it has been published; removals can lag the batch
    # date by a few days, so allow a little slack before the previous snapshot
    fill_time = snapshot_time
    if previous_time is not None:
        batch_dates = issued_df[(issued_df['Date Reissued'] > to_naive_utc(previous_time - timedelta(days=3))) &
                                (issued_df['Date Reissued'] <= to_naive_utc(snapshot_time))]['Date Reissued']
        if not batch_dates.empty:
            fill_time = batch_dates.max().to_pydatetime().replace(tzinfo=timezone.utc)

    waits = {}
    for size in SIZES:
        # Same-size requests in line order (canonical timestamps sort chronologically)
        queue = sorted((item for item in previous_data if item['maximumCidr'] == size),
                       key=lambda item: item['waitListActionDate'])

        removed_flags = [request_key(item) in removed_keys for item in queue]

        served = None
        for position, item in enumerate(queue):
            if removed_flags[position]:
                window = removed_flags[max(0, position + 1 - SERVED_WINDOW):position + 1]
                if sum(window) / len(window) >= SERVED_WINDOW_SHARE:
                    served = item

        if served:
            waited = fill_time - parse_timestamp(served['waitListActionDate'])
            waits[size] = max(waited.total_seconds(), 0) / 86400 / DAYS_PER_MONTH

    return fill_time, waits

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
    current_requests = {request_key(item): item for item in current_data}
    previous_requests = {request_key(item): item for item in previous_data} if previous_data else {}

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
        reference_time = parse_timestamp(reference_time)

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
            action_date = parse_timestamp(action_date_str)

            # Calculate age in days (how long this request has been waiting)
            age_days = (reference_time - action_date).days
            ages_days.append(age_days)

            # Determine CIDR size for this request (use minimumCidr as identifier)
            min_cidr = item.get('minimumCidr')
            cidr_key = str(min_cidr) if min_cidr in [22, 23, 24] else None

            # Convert days to months using average days per month (365.25/12)
            age_months = age_days / DAYS_PER_MONTH

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

def analyze_snapshot(waitlist_data, previous_data, snapshot_time, issued_df, previous_row=None):
    """
    Calculate one row of time-series metrics for a waitlist snapshot.

    Used by both live mode and history reprocessing so the two always agree.

    Args:
        waitlist_data (list): Current waitlist snapshot (normalized)
        previous_data (list): Previous snapshot for churn and fill detection, or None
        snapshot_time (datetime): When the snapshot was taken
        issued_df (DataFrame): Parsed issued blocks from parse_issued_blocks()
        previous_row (dict): Previous CSV row (string values), or None. Supplies the
            previous snapshot time and carries last-fill values forward between batches.

    Returns:
        dict: Metrics keyed by CSV_HEADER column names (values formatted for CSV output)
    """
    # === Churn and Flexibility ===
    # Compare current vs previous to calculate churn and flexibility metrics
    added_by_cidr, removed_by_cidr, added_total, removed_total, flexibility_stats, _ = compare_waitlists(waitlist_data, previous_data)

    # Count requests by CIDR size (using maximumCidr as their preference)
    waitlist_counts = Counter(str(item['maximumCidr']) for item in waitlist_data)

    # Calculate age distribution (how long requests have been waiting)
    age_dist = calculate_age_distribution(waitlist_data, snapshot_time)

    # === Most Recent Fills (observed) ===
    previous_time = parse_timestamp(previous_row['timestamp']) if previous_row and previous_row.get('timestamp') else None
    fill_time, fill_waits = detect_filled_requests(waitlist_data, previous_data, snapshot_time, previous_time, issued_df)

    # Carry the last observed fills forward until the next batch that fills that size
    previous_row = previous_row or {}
    last_fills = {}
    for size in SIZES:
        if size in fill_waits:
            last_fills[size] = (fill_time.date().isoformat(), f'{fill_waits[size]:.1f}')
        else:
            last_fills[size] = (previous_row.get(f'last_fill_date_{size}', ''),
                                previous_row.get(f'last_fill_wait_months_{size}', ''))

    # === Estimated Wait (forward-looking) ===
    # Replay recent batches over the current line to see when a new request would be filled
    batches = recent_quarter_batches(issued_df, snapshot_time)
    supply_rate = calculate_supply_rate(batches)

    # The most recent batch is the later of ARIN's published batches and fills we observed
    # (ARIN publishes its list a few days after removing requests)
    batch_times = [datetime.fromisoformat(date).replace(tzinfo=timezone.utc) for date, _ in last_fills.values() if date]
    published = issued_df.loc[issued_df['Date Reissued'] <= to_naive_utc(snapshot_time), 'Date Reissued']
    if not published.empty:
        batch_times.append(published.max().to_pydatetime().replace(tzinfo=timezone.utc))
    estimated_waits = estimate_waits_by_size(waitlist_data, batches, snapshot_time, max(batch_times, default=None))

    row = {
        'timestamp': format_timestamp(snapshot_time),
        'total_requests': len(waitlist_data),
        'added_total': added_total,
        'removed_total': removed_total,
        'net_change': added_total - removed_total,
        'flexible_requests': flexibility_stats['flexible_requests'],
        'exact_requests': flexibility_stats['exact_requests'],
        'avg_flexibility': f"{flexibility_stats['avg_flexibility']:.2f}",
        'queue_24eq': calculate_queue_24eq(waitlist_data),
        'supply_24eq_per_quarter': f'{supply_rate:.1f}',
    }

    for size in ('22', '23', '24'):
        row[f'requests_{size}'] = waitlist_counts.get(size, 0)
        row[f'added_{size}'] = added_by_cidr.get(size, 0)
        row[f'removed_{size}'] = removed_by_cidr.get(size, 0)

    age_columns = {'0-3_months': '0_3mo', '3-6_months': '3_6mo', '6-12_months': '6_12mo',
                   '12-24_months': '12_24mo', '24+_months': '24plus'}
    for age_bin, column in age_columns.items():
        for size in ('22', '23', '24'):
            row[f'age_{column}_{size}'] = age_dist['bins_by_size'][age_bin][size]

    for size in SIZES:
        waited = estimated_waits[size]
        row[f'estimated_wait_months_{size}'] = f'{waited:.1f}' if waited != float('inf') else 'inf'
        row[f'last_fill_date_{size}'], row[f'last_fill_wait_months_{size}'] = last_fills[size]

    return row

def load_last_csv_row(csv_path):
    """
    Load the most recent row of the time-series CSV.

    Args:
        csv_path (str): Path to the time-series CSV

    Returns:
        dict: Last row keyed by column name, or None if the file is missing or empty
    """
    try:
        with open(csv_path, 'r', encoding='utf-8', newline='') as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        return None
    return rows[-1] if rows else None

def write_issued_by_quarter(issued_df, output_file):
    """
    Write a per-quarter summary of issued address space for the dashboard.

    Every quarter between the first and last issuance is included (empty quarters as
    zero). Columns break issued space down by the size of block it came from.

    Args:
        issued_df (DataFrame): Parsed issued blocks from parse_issued_blocks()
        output_file (str): Path to output CSV (e.g., 'docs/issued_by_quarter.csv')
    """
    quarters = issued_df['Date Reissued'].dt.to_period('Q')
    all_quarters = pd.period_range(quarters.min(), quarters.max(), freq='Q')

    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['quarter', 'blocks_issued', 'eq24_total',
                         'eq24_from_24', 'eq24_from_23', 'eq24_from_22', 'eq24_from_larger'])

        for quarter in all_quarters:
            blocks = issued_df[quarters == quarter]
            eq24 = blocks.groupby('Prefix Size')['Size 24eq'].sum()
            writer.writerow([
                str(quarter),  # e.g. '2026Q3'
                len(blocks),
                int(blocks['Size 24eq'].sum()),
                int(eq24.get(24, 0)),
                int(eq24.get(23, 0)),
                int(eq24.get(22, 0)),
                int(eq24[eq24.index < 22].sum())  # /21 and larger, split to fill requests
            ])

def output_csv(row, include_header=True):
    """
    Output one row of waitlist statistics in CSV format for time-series analysis.

    Args:
        row (dict): Metrics from analyze_snapshot()
        include_header (bool): Whether to output CSV header row

    Output:
        Writes one CSV row to stdout with timestamp and all metrics
    """
    writer = csv.writer(sys.stdout)

    # Header row (optional)
    if include_header:
        writer.writerow(CSV_HEADER)

    writer.writerow([row[column] for column in CSV_HEADER])

def output_text(row):
    """
    Output waitlist summary in human-readable Markdown format.

    This is the default output mode (when --csv is not specified). It provides
    a narrative summary of the waitlist status, changes, and estimated wait times.

    Args:
        row (dict): Metrics from analyze_snapshot()

    Output:
        Prints formatted Markdown text to stdout
    """
    print("### Current Waitlist Summary ###")
    print(f"As of the most recent data, the waitlist has **{row['total_requests']} requests**.")
    print("The requests are for the following network sizes:")
    print(f"* **/22:** {row['requests_22']} requests")
    print(f"* **/23:** {row['requests_23']} requests")
    print(f"* **/24:** {row['requests_24']} requests")

    if row['added_total'] > 0 or row['removed_total'] > 0:
        print("\n" + "---")
        print("### Changes from Previous Snapshot ###")
        print(f"* **Added:** {row['added_total']} requests (/22: {row['added_22']}, /23: {row['added_23']}, /24: {row['added_24']})")
        print(f"* **Removed:** {row['removed_total']} requests (/22: {row['removed_22']}, /23: {row['removed_23']}, /24: {row['removed_24']})")
        print(f"* **Net Change:** {row['net_change']:+d} requests")

    print("\n" + "---")

    print("### Estimated Wait Time ###")
    print("Requests are filled first-come-first-served in roughly quarterly batches, subject to the")
    print("size of the blocks available.")
    print(f"* **{row['queue_24eq']} /24 equivalents** are waiting in line.")
    print(f"* Over the last {SUPPLY_WINDOW_QUARTERS} quarters ARIN issued an average of "
          f"**{row['supply_24eq_per_quarter']} /24 equivalents per quarter** (all block sizes).")
    print("* If future batches look like those quarters, a request joining now would wait approximately:")
    for size in SIZES:
        print(f"    * **/{size}:** {row[f'estimated_wait_months_{size}']} months")

    if any(row[f'last_fill_date_{size}'] for size in SIZES):
        print("\n" + "---")
        print("### Most Recent Fills ###")
        print("In the most recent batch that filled each size, the newest request filled had waited:")
        for size in SIZES:
            if row[f'last_fill_date_{size}']:
                print(f"* **/{size}:** {row[f'last_fill_wait_months_{size}']} months (batch of {row[f'last_fill_date_{size}']})")
            else:
                print(f"* **/{size}:** no fills observed yet")

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
    Get the author date in ISO format for a given commit hash.

    The author date is when the snapshot was taken; the committer date changes
    when history is rebased.

    Args:
        commit_hash (str): Git commit hash

    Returns:
        str: ISO format timestamp of the commit, or None on error
    """
    try:
        result = subprocess.run(
            ['git', 'show', '-s', '--format=%aI', commit_hash],
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
        1. Find all commits that modified waitlist_data.json and sort them by snapshot time
        2. For each commit with a changed snapshot:
           - Extract waitlist JSON at that commit
           - Calculate all metrics (counts, churn, flexibility, age distribution, wait times)
           - Write CSV row with commit timestamp
        3. Result: Complete time-series CSV with one row per snapshot, plus the
           issued-by-quarter summary next to it
    """
    print("Reprocessing git history...", file=sys.stderr)

    # Get all commits for waitlist_data.json
    commits = get_git_commits_for_file('data/waitlist_data.json')

    if not commits:
        print("No commits found for data/waitlist_data.json", file=sys.stderr)
        return

    print(f"Found {len(commits)} commits to process", file=sys.stderr)

    # Fetch issued blocks once; each snapshot only uses blocks issued before its timestamp
    try:
        issued_text = fetch_issued_blocks()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching historical data CSV: {e}; using data/historical_data.csv", file=sys.stderr)
        with open('data/historical_data.csv', 'r', encoding='utf-8') as f:
            issued_text = f.read()
    issued_df = parse_issued_blocks(issued_text)

    # Order snapshots by when they were taken (author date)
    dated_commits = []
    for commit in commits:
        commit_date = get_commit_date(commit)
        if not commit_date:
            print(f"  Could not get date for commit {commit[:8]}, skipping", file=sys.stderr)
            continue
        dated_commits.append((parse_timestamp(commit_date), commit))
    dated_commits.sort()

    # Create output directory if needed (e.g., 'docs/')
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    # Open output file
    with open(output_file, 'w', encoding='utf-8', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(CSV_HEADER)

        # Track previous snapshot for churn and fill detection
        previous_data = None
        previous_row = None

        # === Main Processing Loop ===
        # Process each commit in chronological order to build time-series data
        for i, (snapshot_time, commit) in enumerate(dated_commits):
            print(f"Processing commit {i+1}/{len(dated_commits)}: {commit[:8]}", file=sys.stderr)

            # Extract waitlist_data.json content at this specific commit
            content = get_file_at_commit(commit, 'data/waitlist_data.json')
            if not content:
                print(f"  Could not get file at commit {commit[:8]}, skipping", file=sys.stderr)
                continue

            # Parse the JSON waitlist data from this commit
            try:
                waitlist_data, _ = parse_waitlist_json(content)
            except Exception as e:
                print(f"  Error parsing JSON at commit {commit[:8]}: {e}", file=sys.stderr)
                continue

            # Skip commits that didn't change the snapshot (e.g., reformatting)
            if waitlist_data == previous_data:
                print(f"  Snapshot unchanged at commit {commit[:8]}, skipping", file=sys.stderr)
                continue

            row = analyze_snapshot(waitlist_data, previous_data, snapshot_time, issued_df, previous_row)
            writer.writerow([row[column] for column in CSV_HEADER])

            # Store this snapshot as "previous" for the next iteration
            previous_data = waitlist_data
            previous_row = {column: str(value) for column, value in row.items()}

    write_issued_by_quarter(issued_df, os.path.join(os.path.dirname(output_file), 'issued_by_quarter.csv'))

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

# --- Step 1: Fetch Historical Issued Blocks Data ---
# This data is used to measure supply (address space issued per quarter)

try:
    # Fetch the issued blocks CSV from ARIN
    # This contains all IPv4 blocks that have been issued from the waitlist
    issued_text = fetch_issued_blocks()

    # Save a local copy of the historical data for reference
    with open('data/historical_data.csv', 'w', encoding='utf-8') as f:
        f.write(issued_text)

    issued_df = parse_issued_blocks(issued_text)

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

        # Use the newest request as the snapshot time; no history to carry forward
        snapshot_time = parse_timestamp(data_timestamp)
        previous_row = None

        # Save a standardized copy to data/waitlist_data.json
        with open('data/waitlist_data.json', 'w', encoding='utf-8') as f:
            json.dump(waitlist_data, f, indent=2)
    else:
        # === Live URL Mode (default) ===
        # Fetch the current waitlist JSON from ARIN's public API
        response = requests.get(CURRENT_WAITLIST_URL, timeout=10)
        response.raise_for_status()  # Raise exception for HTTP errors
        snapshot_time = datetime.now(timezone.utc)

        # Save the fetched data to local file for tracking in git
        with open('data/waitlist_data.json', 'w', encoding='utf-8') as f:
            json.dump(json.loads(response.text), f, indent=2)

        # Parse the JSON to extract normalized data
        waitlist_data, _ = parse_waitlist_json(response.text)

        # The previous time-series row supplies the previous snapshot time and the
        # last observed fills to carry forward
        previous_row = load_last_csv_row(args.output_csv)

    # === Load Previous Snapshot (if provided) ===
    # This enables churn tracking (added/removed requests) and fill detection
    previous_data = None
    if args.previous_file:
        previous_data, _ = load_waitlist_data(args.previous_file)

    # === Calculate Metrics ===
    row = analyze_snapshot(waitlist_data, previous_data, snapshot_time, issued_df, previous_row)

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

# --- Step 3: Update Issued Space Summary ---
# Per-quarter supply used by the dashboard (live mode only, alongside the time-series CSV)
if not args.file:
    write_issued_by_quarter(issued_df, os.path.join(os.path.dirname(args.output_csv), 'issued_by_quarter.csv'))

# --- Step 4: Output Results ---
# Output all calculated metrics in the requested format (CSV or human-readable text)

# Choose output format based on --csv flag
if args.csv:
    # === CSV Output Mode ===
    # Output one row of time-series data for appending to tracking CSV
    output_csv(row, include_header=not args.no_header)
else:
    # === Human-Readable Text Output Mode (default) ===
    # Output formatted Markdown summary for human consumption
    output_text(row)
