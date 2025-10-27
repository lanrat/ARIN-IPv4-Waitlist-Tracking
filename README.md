# ARIN IPv4 Waitlist Analyzer

Analyzes ARIN's IPv4 waiting list and estimates wait times based on historical clearing data.

**[View Live Dashboard](https://lanrat.github.io/ARIN-IPv4-Waitlist-Tracking/)**

## Data Sources

- [ARIN IPv4 Waiting List](https://www.arin.net/resources/guide/ipv4/waiting_list/) - Current waitlist status
- [IPv4 Addresses Cleared for Waiting List](https://www.arin.net/resources/guide/ipv4/blocks_cleared/) - Historical clearing data

## Features

- **Waitlist Tracking**: Fetches current waitlist data from ARIN's public API
- **Historical Analysis**: Analyzes historical block clearing patterns to estimate wait times
- **Request Churn Tracking**: Monitors added/removed requests between snapshots
- **Flexibility Analysis**: Tracks how many requesters are willing to accept different block sizes
- **Age Distribution**: Analyzes how long requests have been waiting, broken down by CIDR size
- **Git History Integration**: Uses git commits to track waitlist changes over time
- **Time-Series Data**: Exports comprehensive CSV data (38 columns) for analysis
- **Interactive Dashboard**: Web-based visualizations with 9 charts:
  - Waitlist size over time
  - Historical blocks cleared per quarter
  - Estimated wait time (years)
  - Total processing capacity over time
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

## Output Files

- `docs/waitlist_data.csv` - Time-series data for dashboard (38 columns including counts, churn, flexibility, age distribution)
- `data/waitlist_data.json` - Current waitlist snapshot (tracked in git)
- `data/historical_data.csv` - Historical clearing data (cached from ARIN)

## Dashboard

Open `docs/index.html` in a web browser or visit the [Live Dashboard](https://lanrat.github.io/ARIN-IPv4-Waitlist-Tracking/) to view:

### Current Statistics

- Total requests by CIDR size (/22, /23, /24)
- Recent activity (requests added/removed)
- Flexibility metrics (exact vs flexible requesters)
- Average wait times and queue ages

### Interactive Charts

1. **Current Waitlist Size** - Track total requests and breakdown by block size over time
2. **Historical Blocks Cleared Per Quarter** - Average processing rate by block size
3. **Estimated Wait Time** - Projected years to clear current queue by block size
4. **Total Processing Capacity Over Time** - Combined clearing capacity across all sizes
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

The CSV file contains 38 columns tracking:

- **Basic Counts**: Total requests and breakdown by CIDR size (/22, /23, /24)
- **Churn Metrics**: Added/removed requests by size, net change
- **Flexibility**: Exact vs flexible requests, average flexibility
- **Age by Size**: Age distribution broken down by CIDR size across 5 age ranges (0-3mo, 3-6mo, 6-12mo, 12-24mo, 24+mo)
- **Processing Rates**: Average blocks cleared per quarter by size
- **Wait Time Estimates**: Estimated years to clear queue by size

## Requirements

```bash
pip install -r requirements.txt
```
