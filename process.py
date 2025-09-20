#!/usr/bin/env python3 

import pandas as pd
import json
from collections import Counter
import math
import requests
import io

# --- URLs for the data ---
HISTORICAL_DATA_URL = 'https://www.arin.net/resources/guide/ipv4/blocks_cleared/waiting_list_blocks_issued.csv'
CURRENT_WAITLIST_URL = 'https://accountws.arin.net/public/rest/waitingList'

# --- Step 1: Analyze Historical Data of Cleared Blocks ---

try:
    # Fetch the historical data CSV from the URL
    response = requests.get(HISTORICAL_DATA_URL)
    response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

    # Use io.StringIO to read the CSV content from the response text into pandas
    csv_file = io.StringIO(response.text)
    historical_df = pd.read_csv(csv_file)

    # Clean up column names by removing leading/trailing whitespace
    historical_df.columns = historical_df.columns.str.strip()

    # Extract the prefix size from the 'CIDR Prefix' column
    historical_df['Prefix Size'] = historical_df['CIDR Prefix'].apply(lambda x: int(x.split('/')[1]))

    # Convert 'Date Reissued' to datetime objects for time-series analysis
    historical_df['Date Reissued'] = pd.to_datetime(historical_df['Date Reissued'], format='%m/%d/%y')

    # Group data by quarter and prefix size, then count the occurrences
    quarterly_counts = historical_df.groupby([pd.Grouper(key='Date Reissued', freq='QE'), 'Prefix Size']).size().unstack(fill_value=0)

    # Calculate the average number of blocks cleared per quarter for each size
    avg_cleared_per_quarter = quarterly_counts.mean()
    avg_22_cleared = avg_cleared_per_quarter.get(22, 0)
    avg_23_cleared = avg_cleared_per_quarter.get(23, 0)
    avg_24_cleared = avg_cleared_per_quarter.get(24, 0)

except requests.exceptions.RequestException as e:
    print(f"Error fetching historical data CSV: {e}")
    exit()
except Exception as e:
    print(f"An error occurred while processing historical data: {e}")
    exit()

# --- Step 2: Analyze the Current Waitlist ---

try:
    # Fetch the waitlist JSON from the URL
    response = requests.get(CURRENT_WAITLIST_URL)
    response.raise_for_status() # Raise an exception for bad status codes

    # Parse the JSON content from the response text
    waitlist_data = json.loads(response.text)

    # Count the number of requests for each prefix size based on 'maximumCidr'
    requests_list = [str(item['maximumCidr']) for item in waitlist_data if 'maximumCidr' in item]
    waitlist_counts = Counter(requests_list)

    requests_22 = waitlist_counts.get('22', 0)
    requests_23 = waitlist_counts.get('23', 0)
    requests_24 = waitlist_counts.get('24', 0)
    total_requests = len(waitlist_data)

except requests.exceptions.RequestException as e:
    print(f"Error fetching waitlist JSON: {e}")
    exit()
except json.JSONDecodeError as e:
    print(f"Error parsing waitlist JSON: {e}")
    exit()
except Exception as e:
    print(f"An error occurred while processing the waitlist: {e}")
    exit()

# --- Step 3: Calculate and Display the Estimated Wait Times ---

# Calculate the estimated number of quarters to clear the queue
# Use math.ceil to round up, as a partial quarter is still a full waiting period.
quarters_22 = math.ceil(requests_22 / avg_22_cleared) if avg_22_cleared > 0 else float('inf')
quarters_23 = math.ceil(requests_23 / avg_23_cleared) if avg_23_cleared > 0 else float('inf')
quarters_24 = math.ceil(requests_24 / avg_24_cleared) if avg_24_cleared > 0 else float('inf')

# Convert quarters to years
years_22 = quarters_22 / 4
years_23 = quarters_23 / 4
years_24 = quarters_24 / 4


# --- Step 4: Print the Final Report ---

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