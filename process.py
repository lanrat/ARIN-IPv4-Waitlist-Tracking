#!/usr/bin/env python3

import pandas as pd
import json
from collections import Counter
import math
import requests
import io
import argparse
import csv
import sys
import os
import subprocess
from datetime import datetime

# --- URLs for the data ---
HISTORICAL_DATA_URL = 'https://www.arin.net/resources/guide/ipv4/blocks_cleared/waiting_list_blocks_issued.csv'
CURRENT_WAITLIST_URL = 'https://accountws.arin.net/public/rest/waitingList'

def parse_arguments():
    parser = argparse.ArgumentParser(description='Analyze ARIN IPv4 waitlist and estimate wait times')
    parser.add_argument('--csv', action='store_true', help='Output data in CSV format')
    parser.add_argument('--no-header', action='store_true', help='Skip CSV header (useful for appending to existing files)')
    parser.add_argument('--file', type=str, help='Use local waitlist file (JSON format) instead of fetching from URL')
    parser.add_argument('--previous-file', type=str, help='Previous waitlist file to compare against for tracking adds/removes')
    parser.add_argument('--reprocess-history', action='store_true', help='Reprocess all git history commits and regenerate CSV')
    parser.add_argument('--output-csv', type=str, default='docs/waitlist_data.csv', help='Output CSV file path (default: docs/waitlist_data.csv)')
    return parser.parse_args()

def parse_waitlist_json(json_content):
    """Parse JSON waitlist data and return (data_list, last_timestamp)"""
    data_list = json.loads(json_content)

    # Normalize field names to match current API format
    normalized_data = []
    timestamps = []

    for item in data_list:
        # Handle both old format (lowercase) and new format (camelCase)
        timestamp = item.get('waitListActionDate') or item.get('waitlistactiondate')
        min_cidr = item.get('minimumCidr') or item.get('minimumcidr')
        max_cidr = item.get('maximumCidr') or item.get('maximumcidr')

        if timestamp and max_cidr:
            timestamps.append(timestamp)
            normalized_data.append({
                'waitListActionDate': timestamp,
                'minimumCidr': int(min_cidr) if min_cidr else None,
                'maximumCidr': int(max_cidr)
            })

    # Find the most recent timestamp
    last_timestamp = max(timestamps) if timestamps else None

    return normalized_data, last_timestamp

def load_waitlist_data(file_path):
    """Load waitlist data from local JSON file"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    return parse_waitlist_json(content)

def compare_waitlists(current_data, previous_data):
    """
    Compare current and previous waitlist data to determine added and removed requests.
    Returns (added_by_cidr, removed_by_cidr, added_count, removed_count)
    """
    # Create sets of request identifiers (waitListActionDate) for comparison
    current_requests = {item['waitListActionDate']: item for item in current_data}
    previous_requests = {item['waitListActionDate']: item for item in previous_data} if previous_data else {}

    # Find added and removed requests
    added_ids = set(current_requests.keys()) - set(previous_requests.keys())
    removed_ids = set(previous_requests.keys()) - set(current_requests.keys())

    # Count by CIDR size
    added_by_cidr = Counter()
    removed_by_cidr = Counter()

    for req_id in added_ids:
        cidr = current_requests[req_id]['maximumCidr']
        added_by_cidr[str(cidr)] += 1

    for req_id in removed_ids:
        cidr = previous_requests[req_id]['maximumCidr']
        removed_by_cidr[str(cidr)] += 1

    # Total counts
    added_count = len(added_ids)
    removed_count = len(removed_ids)

    return added_by_cidr, removed_by_cidr, added_count, removed_count

def output_csv(total_requests, requests_22, requests_23, requests_24,
               avg_22_cleared, avg_23_cleared, avg_24_cleared,
               quarters_22, quarters_23, quarters_24, years_22, years_23, years_24,
               added_22=0, added_23=0, added_24=0, added_total=0,
               removed_22=0, removed_23=0, removed_24=0, removed_total=0,
               include_header=True):
    """Output data in CSV format with columns for easy time series tracking"""
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
            'avg_22_cleared_per_quarter',
            'avg_23_cleared_per_quarter',
            'avg_24_cleared_per_quarter',
            'estimated_quarters_22',
            'estimated_years_22',
            'estimated_quarters_23',
            'estimated_years_23',
            'estimated_quarters_24',
            'estimated_years_24'
        ])

    # Use file timestamp if available, otherwise current time
    timestamp = data_timestamp if 'data_timestamp' in globals() and data_timestamp else datetime.now().isoformat()

    # Calculate net change
    net_change = added_total - removed_total

    # Data row
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
        f'{avg_22_cleared:.1f}',
        f'{avg_23_cleared:.1f}',
        f'{avg_24_cleared:.1f}',
        quarters_22 if quarters_22 != float('inf') else 'inf',
        f'{years_22:.1f}' if years_22 != float('inf') else 'inf',
        quarters_23 if quarters_23 != float('inf') else 'inf',
        f'{years_23:.1f}' if years_23 != float('inf') else 'inf',
        quarters_24 if quarters_24 != float('inf') else 'inf',
        f'{years_24:.1f}' if years_24 != float('inf') else 'inf'
    ])

def output_text(total_requests, requests_22, requests_23, requests_24,
                avg_22_cleared, avg_23_cleared, avg_24_cleared,
                quarters_22, quarters_23, quarters_24, years_22, years_23, years_24,
                added_22=0, added_23=0, added_24=0, added_total=0,
                removed_22=0, removed_23=0, removed_24=0, removed_total=0):
    """Output data in human-readable text format"""
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
    """Get all git commits that modified a specific file, in chronological order"""
    try:
        # Get list of commits that modified the file, in reverse chronological order
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
    """Get the contents of a file at a specific commit"""
    try:
        result = subprocess.run(
            ['git', 'show', f'{commit_hash}:{file_path}'],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return None

def get_commit_date(commit_hash):
    """Get the commit date in ISO format"""
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
    """Reprocess all git history commits and regenerate the CSV file"""
    print("Reprocessing git history...", file=sys.stderr)

    # Get all commits for waitlist_data.json
    commits = get_git_commits_for_file('data/waitlist_data.json')

    if not commits:
        print("No commits found for data/waitlist_data.json", file=sys.stderr)
        return

    print(f"Found {len(commits)} commits to process", file=sys.stderr)

    # Create output directory if needed
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
            'avg_22_cleared_per_quarter',
            'avg_23_cleared_per_quarter',
            'avg_24_cleared_per_quarter',
            'estimated_quarters_22',
            'estimated_years_22',
            'estimated_quarters_23',
            'estimated_years_23',
            'estimated_quarters_24',
            'estimated_years_24'
        ])

        previous_data = None

        # Process each commit
        for i, commit in enumerate(commits):
            print(f"Processing commit {i+1}/{len(commits)}: {commit[:8]}", file=sys.stderr)

            # Get file content at this commit
            content = get_file_at_commit(commit, 'data/waitlist_data.json')
            if not content:
                print(f"  Could not get file at commit {commit[:8]}, skipping", file=sys.stderr)
                continue

            # Get commit date
            commit_date = get_commit_date(commit)
            if not commit_date:
                print(f"  Could not get date for commit {commit[:8]}, skipping", file=sys.stderr)
                continue

            # Parse waitlist data
            try:
                waitlist_data, _ = parse_waitlist_json(content)
            except Exception as e:
                print(f"  Error parsing JSON at commit {commit[:8]}: {e}", file=sys.stderr)
                continue

            # Compare with previous data
            added_by_cidr, removed_by_cidr, added_total, removed_total = compare_waitlists(waitlist_data, previous_data)

            # Count by size
            requests_list = [str(item['maximumCidr']) for item in waitlist_data if 'maximumCidr' in item]
            waitlist_counts = Counter(requests_list)

            requests_22 = waitlist_counts.get('22', 0)
            requests_23 = waitlist_counts.get('23', 0)
            requests_24 = waitlist_counts.get('24', 0)
            total_requests = len(waitlist_data)

            added_22 = added_by_cidr.get('22', 0)
            added_23 = added_by_cidr.get('23', 0)
            added_24 = added_by_cidr.get('24', 0)

            removed_22 = removed_by_cidr.get('22', 0)
            removed_23 = removed_by_cidr.get('23', 0)
            removed_24 = removed_by_cidr.get('24', 0)

            # Load historical data and calculate stats
            # (We need to do this for each commit with proper timestamp cutoff)
            try:
                # Fetch the historical data CSV (this doesn't change based on commit)
                response = requests.get(HISTORICAL_DATA_URL, timeout=10)
                response.raise_for_status()

                csv_file = io.StringIO(response.text)
                historical_df = pd.read_csv(csv_file)
                historical_df.columns = historical_df.columns.str.strip()
                historical_df['Prefix Size'] = historical_df['CIDR Prefix'].apply(lambda x: int(x.split('/')[1]))
                historical_df['Date Reissued'] = pd.to_datetime(historical_df['Date Reissued'], format='%m/%d/%y')

                # Apply timestamp cutoff
                cutoff_date = pd.to_datetime(commit_date).tz_localize(None)
                historical_df = historical_df[historical_df['Date Reissued'] <= cutoff_date]

                # Calculate averages
                quarterly_counts = historical_df.groupby([pd.Grouper(key='Date Reissued', freq='QE'), 'Prefix Size']).size().unstack(fill_value=0)
                avg_cleared_per_quarter = quarterly_counts.mean()
                avg_22_cleared = avg_cleared_per_quarter.get(22, 0)
                avg_23_cleared = avg_cleared_per_quarter.get(23, 0)
                avg_24_cleared = avg_cleared_per_quarter.get(24, 0)

            except Exception as e:
                print(f"  Error fetching historical data: {e}", file=sys.stderr)
                avg_22_cleared = avg_23_cleared = avg_24_cleared = 0

            # Calculate wait times
            quarters_22 = math.ceil(requests_22 / avg_22_cleared) if avg_22_cleared > 0 else float('inf')
            quarters_23 = math.ceil(requests_23 / avg_23_cleared) if avg_23_cleared > 0 else float('inf')
            quarters_24 = math.ceil(requests_24 / avg_24_cleared) if avg_24_cleared > 0 else float('inf')

            years_22 = quarters_22 / 4
            years_23 = quarters_23 / 4
            years_24 = quarters_24 / 4

            # Write to CSV
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
                f'{avg_22_cleared:.1f}',
                f'{avg_23_cleared:.1f}',
                f'{avg_24_cleared:.1f}',
                quarters_22 if quarters_22 != float('inf') else 'inf',
                f'{years_22:.1f}' if years_22 != float('inf') else 'inf',
                quarters_23 if quarters_23 != float('inf') else 'inf',
                f'{years_23:.1f}' if years_23 != float('inf') else 'inf',
                quarters_24 if quarters_24 != float('inf') else 'inf',
                f'{years_24:.1f}' if years_24 != float('inf') else 'inf'
            ])

            # Store for next iteration
            previous_data = waitlist_data

    print(f"Reprocessing complete! Output written to {output_file}", file=sys.stderr)

# Parse command line arguments
args = parse_arguments()

# Handle reprocessing mode
if args.reprocess_history:
    reprocess_git_history(args.output_csv)
    sys.exit(0)

# Create data directory if it doesn't exist
os.makedirs('data', exist_ok=True)

# --- Step 1: Analyze Historical Data of Cleared Blocks ---

try:
    # Fetch the historical data CSV from the URL
    response = requests.get(HISTORICAL_DATA_URL, timeout=10)
    response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

    # Save the historical CSV data to a local file
    with open('data/historical_data.csv', 'w', encoding='utf-8') as f:
        f.write(response.text)

    # Use io.StringIO to read the CSV content from the response text into pandas
    csv_file = io.StringIO(response.text)
    historical_df = pd.read_csv(csv_file)

    # Clean up column names by removing leading/trailing whitespace
    historical_df.columns = historical_df.columns.str.strip()

    # Extract the prefix size from the 'CIDR Prefix' column
    historical_df['Prefix Size'] = historical_df['CIDR Prefix'].apply(lambda x: int(x.split('/')[1]))

    # Convert 'Date Reissued' to datetime objects for time-series analysis
    historical_df['Date Reissued'] = pd.to_datetime(historical_df['Date Reissued'], format='%m/%d/%y')

    # Store historical_df for later processing after we get the timestamp

except requests.exceptions.RequestException as e:
    print(f"Error fetching historical data CSV: {e}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"An error occurred while processing historical data: {e}", file=sys.stderr)
    sys.exit(1)

# --- Step 2: Analyze the Current Waitlist ---

try:
    if args.file:
        # Load from local file
        waitlist_data, data_timestamp = load_waitlist_data(args.file)

        # Save the waitlist data to a local file (convert to JSON format if needed)
        with open('data/waitlist_data.json', 'w', encoding='utf-8') as f:
            json.dump(waitlist_data, f, indent=2)
    else:
        # Fetch the waitlist JSON from the URL
        response = requests.get(CURRENT_WAITLIST_URL, timeout=10)
        response.raise_for_status() # Raise an exception for bad status codes

        # Save the waitlist JSON data to a local file with formatting
        with open('data/waitlist_data.json', 'w', encoding='utf-8') as f:
            json.dump(json.loads(response.text), f, indent=2)

        # Parse the JSON content from the response text
        waitlist_data, data_timestamp = parse_waitlist_json(response.text)

    # Load previous data if specified
    previous_data = None
    if args.previous_file:
        previous_data, _ = load_waitlist_data(args.previous_file)

    # Compare with previous data to get adds/removes
    added_by_cidr, removed_by_cidr, added_total, removed_total = compare_waitlists(waitlist_data, previous_data)

    # Count the number of requests for each prefix size based on 'maximumCidr'
    requests_list = [str(item['maximumCidr']) for item in waitlist_data if 'maximumCidr' in item]
    waitlist_counts = Counter(requests_list)

    requests_22 = waitlist_counts.get('22', 0)
    requests_23 = waitlist_counts.get('23', 0)
    requests_24 = waitlist_counts.get('24', 0)
    total_requests = len(waitlist_data)

    # Get added/removed counts by CIDR size
    added_22 = added_by_cidr.get('22', 0)
    added_23 = added_by_cidr.get('23', 0)
    added_24 = added_by_cidr.get('24', 0)

    removed_22 = removed_by_cidr.get('22', 0)
    removed_23 = removed_by_cidr.get('23', 0)
    removed_24 = removed_by_cidr.get('24', 0)

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

# --- Step 3: Process Historical Data with Timestamp Cutoff ---

# Apply timestamp cutoff if using a local file (for historical analysis)
if args.file and data_timestamp:
    # Convert the waitlist timestamp to datetime for comparison (remove timezone info to match historical data)
    cutoff_date = pd.to_datetime(data_timestamp).tz_localize(None)
    print(f"Using timestamp cutoff: {cutoff_date}", file=sys.stderr)

    # Filter historical data to only include entries before the waitlist snapshot
    historical_df = historical_df[historical_df['Date Reissued'] <= cutoff_date]

# Group data by quarter and prefix size, then count the occurrences
quarterly_counts = historical_df.groupby([pd.Grouper(key='Date Reissued', freq='QE'), 'Prefix Size']).size().unstack(fill_value=0)

# Calculate the average number of blocks cleared per quarter for each size
avg_cleared_per_quarter = quarterly_counts.mean()
avg_22_cleared = avg_cleared_per_quarter.get(22, 0)
avg_23_cleared = avg_cleared_per_quarter.get(23, 0)
avg_24_cleared = avg_cleared_per_quarter.get(24, 0)

# --- Step 4: Calculate and Display the Estimated Wait Times ---

# Calculate the estimated number of quarters to clear the queue
# Use math.ceil to round up, as a partial quarter is still a full waiting period.
quarters_22 = math.ceil(requests_22 / avg_22_cleared) if avg_22_cleared > 0 else float('inf')
quarters_23 = math.ceil(requests_23 / avg_23_cleared) if avg_23_cleared > 0 else float('inf')
quarters_24 = math.ceil(requests_24 / avg_24_cleared) if avg_24_cleared > 0 else float('inf')

# Convert quarters to years
years_22 = quarters_22 / 4
years_23 = quarters_23 / 4
years_24 = quarters_24 / 4


# --- Step 5: Output the Final Report ---

# Choose output format based on command line arguments
if args.csv:
    output_csv(total_requests, requests_22, requests_23, requests_24,
               avg_22_cleared, avg_23_cleared, avg_24_cleared,
               quarters_22, quarters_23, quarters_24, years_22, years_23, years_24,
               added_22, added_23, added_24, added_total,
               removed_22, removed_23, removed_24, removed_total,
               include_header=not args.no_header)
else:
    output_text(total_requests, requests_22, requests_23, requests_24,
                avg_22_cleared, avg_23_cleared, avg_24_cleared,
                quarters_22, quarters_23, quarters_24, years_22, years_23, years_24,
                added_22, added_23, added_24, added_total,
                removed_22, removed_23, removed_24, removed_total)
