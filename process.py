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
from datetime import datetime

# --- URLs for the data ---
HISTORICAL_DATA_URL = 'https://www.arin.net/resources/guide/ipv4/blocks_cleared/waiting_list_blocks_issued.csv'
CURRENT_WAITLIST_URL = 'https://accountws.arin.net/public/rest/waitingList'

def parse_arguments():
    parser = argparse.ArgumentParser(description='Analyze ARIN IPv4 waitlist and estimate wait times')
    parser.add_argument('--csv', action='store_true', help='Output data in CSV format')
    parser.add_argument('--no-header', action='store_true', help='Skip CSV header (useful for appending to existing files)')
    parser.add_argument('--file', type=str, help='Use local waitlist file (JSON format) instead of fetching from URL')
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

def output_csv(total_requests, requests_22, requests_23, requests_24,
               avg_22_cleared, avg_23_cleared, avg_24_cleared,
               quarters_22, quarters_23, quarters_24, years_22, years_23, years_24, include_header=True):
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

    # Data row
    writer.writerow([
        timestamp,
        total_requests,
        requests_22,
        requests_23,
        requests_24,
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
                quarters_22, quarters_23, quarters_24, years_22, years_23, years_24):
    """Output data in human-readable text format"""
    print("### Current Waitlist Summary ###")
    print(f"As of the most recent data, the waitlist has **{total_requests} requests**.")
    print("The requests are for the following network sizes:")
    print(f"* **/22:** {requests_22} requests")
    print(f"* **/23:** {requests_23} requests")
    print(f"* **/24:** {requests_24} requests")
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

# Parse command line arguments
args = parse_arguments()

# Create data directory if it doesn't exist
os.makedirs('data', exist_ok=True)

# --- Step 1: Analyze Historical Data of Cleared Blocks ---

try:
    # Fetch the historical data CSV from the URL
    response = requests.get(HISTORICAL_DATA_URL)
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
        response = requests.get(CURRENT_WAITLIST_URL)
        response.raise_for_status() # Raise an exception for bad status codes

        # Save the waitlist JSON data to a local file
        with open('data/waitlist_data.json', 'w', encoding='utf-8') as f:
            f.write(response.text)

        # Parse the JSON content from the response text
        waitlist_data, data_timestamp = parse_waitlist_json(response.text)

    # Count the number of requests for each prefix size based on 'maximumCidr'
    requests_list = [str(item['maximumCidr']) for item in waitlist_data if 'maximumCidr' in item]
    waitlist_counts = Counter(requests_list)

    requests_22 = waitlist_counts.get('22', 0)
    requests_23 = waitlist_counts.get('23', 0)
    requests_24 = waitlist_counts.get('24', 0)
    total_requests = len(waitlist_data)

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


# --- Step 4: Output the Final Report ---

# Choose output format based on command line arguments
if args.csv:
    output_csv(total_requests, requests_22, requests_23, requests_24,
               avg_22_cleared, avg_23_cleared, avg_24_cleared,
               quarters_22, quarters_23, quarters_24, years_22, years_23, years_24,
               include_header=not args.no_header)
else:
    output_text(total_requests, requests_22, requests_23, requests_24,
                avg_22_cleared, avg_23_cleared, avg_24_cleared,
                quarters_22, quarters_23, quarters_24, years_22, years_23, years_24)