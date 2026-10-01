# ARIN IPv4 Waitlist Analyzer

Analyzes ARIN's IPv4 waiting list and estimates wait times based on the address space ARIN has issued to it.

**[View Live Dashboard](https://lanrat.github.io/ARIN-IPv4-Waitlist-Tracking/)**

## Data Sources

- [ARIN IPv4 Waiting List](https://www.arin.net/resources/guide/ipv4/waiting_list/) - Current waitlist status
- [IPv4 Addresses Cleared for Waiting List](https://www.arin.net/resources/guide/ipv4/blocks_cleared/) - Historical clearing data

## Features

- **Waitlist Tracking**: Fetches current waitlist data from ARIN's public API
- **Wait Time Estimates**: Estimates the wait for a new request from its place in line and the address space ARIN issues per quarter
- **Observed Waits**: Detects each issuance batch and records how long the most recently filled requests actually waited
- **Request Churn Tracking**: Monitors added/removed requests between snapshots
- **Flexibility Analysis**: Tracks how many requesters are willing to accept different block sizes
- **Age Distribution**: Analyzes how long requests have been waiting, broken down by CIDR size
- **Git History Integration**: Uses git commits to track waitlist changes over time
- **Time-Series Data**: Exports comprehensive CSV data (41 columns) for analysis
- **Interactive Dashboard**: Web-based visualizations with 9 charts:
  - Waitlist size over time
  - Estimated vs observed wait time (months)
  - Address space issued per quarter
  - Address space waiting vs issued
  - Request activity (added vs removed)
  - Efficiency ratio (removed/added)
  - Block size net change competition
  - Request flexibility distribution (pie chart)
  - Current request age distribution (stacked bar chart)

## Usage

### Basic Analysis

```bash
# Human-readable text output
python process.py

# CSV output (for appending to time-series data)
python process.py --csv

# CSV output without header (for appending to existing file)
python process.py --csv --no-header
```

### Tracking Changes

```bash
# Compare current snapshot with previous to track added/removed requests
python process.py --csv --no-header --previous-file data/previous_waitlist_data.json
```

### Historical Analysis

```bash
# Analyze a historical snapshot
python process.py --file data/historical/snapshot.json --csv

# Reprocess entire git history to regenerate CSV with all historical snapshots
python process.py --reprocess-history --output-csv docs/waitlist_data.csv
```

## How Wait Times Are Estimated

ARIN fills the waitlist first-come-first-served (by `waitListActionDate`) in roughly quarterly batches.
Its [issued blocks list](https://www.arin.net/resources/guide/ipv4/blocks_cleared/) includes large blocks
(/15–/21) that are split to fill many /22–/24 requests, so supply is measured as address space in
/24 equivalents (/22 = 4, /16 = 256) across all block sizes, not by counting /22–/24 rows.

- **Estimated wait (joining now)** = /24 equivalents already waiting ÷ average /24 equivalents issued
  per quarter over the last 8 quarters (quarters with no issuance count as zero).
- **Most recent fills** = for each block size, how long the newest request filled in the latest batch
  had waited. Batches are detected from snapshot diffs (10+ removals); a request counts as filled when
  at least 8 of the 10 same-size requests up to it in line were removed, which ignores withdrawals and
  requests stuck at the front of the line.

The estimate assumes future batches match the recent average, and batch sizes vary a lot
(165 to 1,471 /24 equivalents per batch over 2025–2026), so treat it as a rough guide and compare it
with the observed waits.

## Output Files

- `docs/waitlist_data.csv` - Time-series data for dashboard (41 columns including counts, churn, flexibility, age distribution, wait times)
- `docs/issued_by_quarter.csv` - Address space issued per quarter by source block size
- `data/waitlist_data.json` - Current waitlist snapshot (tracked in git)
- `data/historical_data.csv` - Historical issued blocks data (cached from ARIN)

## Dashboard

Open `docs/index.html` in a web browser or visit the [Live Dashboard](https://lanrat.github.io/ARIN-IPv4-Waitlist-Tracking/) to view:

### Current Statistics

- Total requests by CIDR size (/22, /23, /24)
- Recent activity (requests added/removed)
- Flexibility metrics (exact vs flexible requesters)
- Estimated wait for a new request and observed waits of the most recent fills

### Interactive Charts

1. **Current Waitlist Size** - Track total requests and breakdown by block size over time
2. **Wait Time** - Estimated wait for a new request vs how long recently filled requests actually waited
3. **Address Space Issued Per Quarter** - Supply by quarter, broken down by source block size
4. **Waiting vs Issued** - /24 equivalents waiting compared with the average issued per quarter
5. **Request Activity** - Compare added vs removed requests over time
6. **Efficiency Ratio** - Monitor removed/added ratio with break-even line at 1.0
7. **Block Size Net Change Competition** - Net change by CIDR size (/22, /23, /24)
8. **Request Flexibility Distribution** - Pie chart of exact vs flexible requests
9. **Current Request Age Distribution** - Stacked bar chart showing age ranges by block size

## Automation

GitHub Action runs **weekly** to automatically:

1. Fetch current waitlist data
2. Compare with previous snapshot
3. Calculate all metrics
4. Update CSV and commit changes
5. Deploy updated dashboard to GitHub Pages

Manual runs available via workflow dispatch.

## Data Columns

The CSV file contains 41 columns tracking:

- **Basic Counts**: Total requests and breakdown by CIDR size (/22, /23, /24)
- **Churn Metrics**: Added/removed requests by size, net change
- **Flexibility**: Exact vs flexible requests, average flexibility
- **Age by Size**: Age distribution broken down by CIDR size across 5 age ranges (0-3mo, 3-6mo, 6-12mo, 12-24mo, 24+mo)
- **Supply and Queue**: /24 equivalents waiting and average /24 equivalents issued per quarter
- **Wait Times**: Estimated wait (months) for a request joining now, and the date and wait of the most recent fill by size

## Requirements

```bash
pip install -r requirements.txt
```
