# ARIN IPv4 Waitlist Analyzer

Analyzes ARIN's IPv4 waiting list and estimates wait times based on historical clearing data.

**[View Live Dashboard](https://lanrat.github.io/ARIN-IPv4-Waitlist-Tracking/)**

## Data Sources

- [ARIN IPv4 Waiting List](https://www.arin.net/resources/guide/ipv4/waiting_list/) - Current waitlist status
- [IPv4 Addresses Cleared for Waiting List](https://www.arin.net/resources/guide/ipv4/blocks_cleared/) - Historical clearing data

## Features

- Fetches current waitlist data from ARIN's public API
- Analyzes historical block clearing patterns
- Calculates estimated wait times by CIDR size (/22, /23, /24)
- Exports data to CSV format for time-series analysis
- Interactive web dashboard for visualization

## Usage

### Basic Analysis

```bash
python process.py                    # Text output
python process.py --csv              # CSV output
```

### Historical Data

```bash
python process.py --file snapshot.json --csv  # Analyze historical snapshot
```

## Output Files

- `docs/waitlist_data.csv` - Time-series data for dashboard
- `data/waitlist_data.json` - Current waitlist snapshot
- `data/historical_data.csv` - Historical clearing data

## Dashboard

Open `docs/index.html` in a web browser to view interactive charts showing:

- Current waitlist size over time
- Historical blocks cleared per quarter
- Estimated wait times

## Automation

GitHub Action runs monthly to automatically update data. Manual runs available via workflow dispatch.

## Requirements

```bash
pip install -r requirements.txt
```
