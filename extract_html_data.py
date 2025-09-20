#!/usr/bin/env python3

import re
import json
import sys
import os
import argparse
from datetime import datetime
import pytz

def parse_arguments():
    parser = argparse.ArgumentParser(description='Extract IPv4 waiting list data from HTML file and convert to JSON')
    parser.add_argument('html_file', help='Path to the HTML file to process')
    return parser.parse_args()

def parse_datetime(date_str):
    """
    Convert from 'Thu, 23 Jun 2022, 14:17:46 EDT' to ISO 8601 format
    """
    # Remove the day of week and extra spaces
    date_str = re.sub(r'^[A-Za-z]+,\s*', '', date_str)

    # Handle "Sept" -> "Sep" conversion for proper parsing
    date_str = date_str.replace('Sept', 'Sep')

    # Parse the datetime
    try:
        # Handle EDT/EST timezone
        if date_str.endswith(' EDT'):
            dt = datetime.strptime(date_str[:-4], '%d %b %Y, %H:%M:%S')
            # EDT is UTC-4
            dt = dt.replace(tzinfo=pytz.timezone('US/Eastern'))
        elif date_str.endswith(' EST'):
            dt = datetime.strptime(date_str[:-4], '%d %b %Y, %H:%M:%S')
            # EST is UTC-5
            dt = dt.replace(tzinfo=pytz.timezone('US/Eastern'))
        else:
            # Assume EDT if no timezone specified
            dt = datetime.strptime(date_str, '%d %b %Y, %H:%M:%S')
            dt = dt.replace(tzinfo=pytz.timezone('US/Eastern'))

        return dt.isoformat()
    except Exception as e:
        print(f"Error parsing date '{date_str}': {e}", file=sys.stderr)
        return None

def extract_table_data(html_file_path):
    """
    Extract table data from the HTML file
    """
    with open(html_file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find the tbody with id="wait_list"
    tbody_pattern = r'<tbody id="wait_list"[^>]*>(.*?)</tbody>'
    tbody_match = re.search(tbody_pattern, content, re.DOTALL)

    if not tbody_match:
        print("Could not find tbody with id='wait_list'")
        return []

    tbody_content = tbody_match.group(1)

    # Extract all table rows
    tr_pattern = r'<tr[^>]*>(.*?)</tr>'
    rows = re.findall(tr_pattern, tbody_content, re.DOTALL)

    extracted_data = []

    for row in rows:
        # Extract table cells
        td_pattern = r'<td[^>]*>(.*?)</td>'
        cells = re.findall(td_pattern, row, re.DOTALL)

        if len(cells) >= 4:
            # Extract the text content from each cell
            position = re.sub(r'<[^>]+>', '', cells[0]).strip()
            date_time = re.sub(r'<[^>]+>', '', cells[1]).strip()
            max_prefix = re.sub(r'<[^>]+>', '', cells[2]).strip()
            min_prefix = re.sub(r'<[^>]+>', '', cells[3]).strip()

            # Convert date to ISO format
            iso_date = parse_datetime(date_time)

            if iso_date:
                # Extract CIDR numbers (remove the '/' prefix)
                max_cidr = int(max_prefix.replace('/', '')) if max_prefix.startswith('/') else None
                min_cidr = int(min_prefix.replace('/', '')) if min_prefix.startswith('/') else None

                if max_cidr is not None and min_cidr is not None:
                    extracted_data.append({
                        'waitlistactiondate': iso_date,
                        'maximumcidr': str(max_cidr),
                        'minimumcidr': str(min_cidr)
                    })

    return extracted_data

if __name__ == "__main__":
    args = parse_arguments()

    # Check if input file exists
    if not os.path.exists(args.html_file):
        print(f"Error: File '{args.html_file}' not found", file=sys.stderr)
        sys.exit(1)

    # Generate output filename (same name as input but with .json extension)
    base_name = os.path.splitext(args.html_file)[0]
    output_file = f"{base_name}.json"

    try:
        print(f"Extracting data from '{args.html_file}'...", file=sys.stderr)
        data = extract_table_data(args.html_file)

        print(f"Extracted {len(data)} records", file=sys.stderr)

        if data:
            print("Sample record:", file=sys.stderr)
            print(json.dumps(data[0], indent=2), file=sys.stderr)

            # Write to JSON file
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

            print(f"Data written to '{output_file}'", file=sys.stderr)
        else:
            print("No data extracted", file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        print(f"Error processing file: {e}", file=sys.stderr)
        sys.exit(1)