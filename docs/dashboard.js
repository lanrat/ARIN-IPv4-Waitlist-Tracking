/**
 * ARIN IPv4 Waitlist Dashboard - JavaScript
 *
 * This script powers the interactive dashboard for visualizing ARIN's IPv4 waitlist data.
 * It fetches time-series data from a CSV file, processes it, and creates multiple Chart.js
 * visualizations to track waitlist trends, request churn, flexibility, and age distribution.
 *
 * Key Features:
 * - CSV parsing and data normalization
 * - Dark/light theme support with dynamic color switching
 * - 7 interactive charts tracking different metrics
 * - Real-time statistics cards
 * - Responsive design for mobile and desktop
 *
 * Data Sources: docs/waitlist_data.csv (time-series, one row per snapshot)
 *               docs/issued_by_quarter.csv (address space ARIN issued per quarter)
 *               docs/fills_by_batch.csv (how long filled requests waited, per batch and size)
 * Chart Library: Chart.js with Time and Adapter-Date-Fns plugins
 */

// ============================================================================
// === CONFIGURATION ===
// ============================================================================

/**
 * Color scheme for CIDR sizes across all charts
 * These colors are consistently used to represent /22, /23, and /24 blocks
 */
const colors = {
    '/22': '#ff6384',  // Red/Pink - Largest blocks (1024 IPs)
    '/23': '#36a2eb',  // Blue - Medium blocks (512 IPs)
    '/24': '#4bc0c0'   // Teal - Smallest blocks (256 IPs)
};

// ============================================================================
// === DATA PROCESSING FUNCTIONS ===
// ============================================================================

/**
 * Parse CSV text into an array of objects
 *
 * Converts raw CSV text into structured data with each row as an object
 * where keys are column headers and values are the corresponding cell values.
 * Also handles malformed rows and sorts data chronologically.
 *
 * @param {string} csvText - Raw CSV text with header row and data rows
 * @returns {Array<Object>} Array of data objects sorted by timestamp
 */
function parseCSV(csvText) {
    // Split into lines and filter out empty lines
    const lines = csvText.trim().split('\n').filter(line => line.trim() !== '');

    // Extract header row (column names)
    const headers = lines[0].split(',').map(h => h.trim());
    const data = [];

    // Parse each data row (skip header at index 0)
    for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (line === '') continue;  // Skip empty lines

        // Split row into values
        const values = line.split(',').map(v => v.trim());

        // Validate row has correct number of columns (skip malformed rows)
        if (values.length !== headers.length) continue;

        // Create object mapping headers to values
        const row = {};
        headers.forEach((header, index) => {
            row[header] = values[index];
        });
        data.push(row);
    }

    // Sort data by timestamp to ensure proper chronological order
    // This is important for time-series charts to render correctly
    if (headers.includes('timestamp')) {
        data.sort((a, b) => {
            const dateA = new Date(a.timestamp);
            const dateB = new Date(b.timestamp);
            return dateA - dateB;  // Ascending order (oldest first)
        });
    }

    console.log('Parsed and sorted data:', data);  // Debug: verify parsing
    return data;
}

/**
 * Create Chart.js datasets from parsed CSV data
 *
 * Transforms CSV data into Chart.js dataset format with proper time-series structure.
 * Creates one dataset per CIDR size (/22, /23, /24) with consistent colors.
 *
 * @param {Array<Object>} data - Parsed CSV data array
 * @param {Object} valueColumns - Mapping of CIDR sizes to column names
 *                                Example: {'/22': 'requests_22', '/23': 'requests_23', '/24': 'requests_24'}
 * @param {string} label - Base label for datasets (e.g., "Requests")
 * @returns {Array<Object>} Array of Chart.js dataset objects
 */
function createDatasets(data, valueColumns, label) {
    const datasets = [];

    // Create a dataset for each CIDR size
    Object.keys(colors).forEach(size => {
        const column = valueColumns[size];
        if (column) {
            // Transform data into Chart.js time-series format {x: date, y: value}
            const chartData = data.map(row => {
                const value = parseFloat(row[column]);
                console.log(`${column} for ${size}: "${row[column]}" -> ${value}`);  // Debug
                return {
                    x: new Date(row.timestamp),  // X-axis: time
                    y: isNaN(value) ? 0 : value   // Y-axis: metric value (default to 0 if invalid)
                };
            });

            // Push dataset with consistent styling
            datasets.push({
                label: `${label} ${size}`,           // e.g., "Requests /22"
                data: chartData,
                borderColor: colors[size],           // Line color
                backgroundColor: colors[size] + '20', // Fill color (with 20% opacity via hex)
                tension: 0.1                         // Slight curve to lines
            });
        }
    });

    return datasets;
}

// ============================================================================
// === THEME SUPPORT ===
// ============================================================================

/**
 * Get theme-appropriate colors for chart elements
 *
 * Detects user's system color scheme preference (dark/light mode) and
 * returns appropriate colors for text and grid lines. This ensures charts
 * are readable in both dark and light modes.
 *
 * @returns {Object} Object with 'text' and 'grid' color properties
 */
function getThemeColors() {
    // Check system dark mode preference
    const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    return {
        text: isDark ? '#e0e0e0' : '#333',     // Light gray text for dark mode, dark text for light mode
        grid: isDark ? '#404040' : '#dee2e6'   // Subtle grid lines appropriate for each theme
    };
}

// ============================================================================
// === CHART CREATION FUNCTIONS ===
// ============================================================================

/**
 * Create a basic line chart for time-series data
 *
 * Generic function for creating line charts with consistent styling and
 * time-based x-axis. Used for charts that show trends over time.
 *
 * @param {string} canvasId - ID of the canvas element to render chart into
 * @param {string} title - Chart title displayed at top
 * @param {Array<Object>} data - Parsed CSV data
 * @param {Object} valueColumns - Column mapping for CIDR sizes
 * @param {string} yAxisLabel - Label for Y-axis
 * @returns {Chart} Chart.js chart instance
 */
function createChart(canvasId, title, data, valueColumns, yAxisLabel) {
    try {
        // Get canvas 2D rendering context
        const ctx = document.getElementById(canvasId).getContext('2d');

        // Create datasets for each CIDR size
        const datasets = createDatasets(data, valueColumns, '');

        // Get colors appropriate for current theme
        const themeColors = getThemeColors();

        // Create and return Chart.js instance
        return new Chart(ctx, {
        type: 'line',
        data: { datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: {
                    display: true,
                    text: title,
                    color: themeColors.text
                },
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        color: themeColors.text
                    }
                }
            },
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'day',
                        displayFormats: {
                            day: 'MMM dd, yyyy'
                        }
                    },
                    title: {
                        display: true,
                        text: 'Time',
                        color: themeColors.text
                    },
                    ticks: {
                        color: themeColors.text
                    },
                    grid: {
                        color: themeColors.grid
                    }
                },
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: yAxisLabel,
                        color: themeColors.text
                    },
                    ticks: {
                        color: themeColors.text
                    },
                    grid: {
                        color: themeColors.grid
                    }
                }
            }
        }
    });
    } catch (error) {
        console.error(`Error creating chart ${canvasId}:`, error);
        throw error;
    }
}

/**
 * Create a line chart from prepared datasets with the standard time-series axes
 *
 * @param {string} canvasId - ID of the canvas element to render chart into
 * @param {string} title - Chart title displayed at top
 * @param {Array<Object>} datasets - Chart.js datasets with {x: Date, y: number} points
 * @param {string} yAxisLabel - Label for Y-axis
 * @returns {Chart} Chart.js chart instance
 */
function createTimeSeriesChart(canvasId, title, datasets, yAxisLabel) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    const themeColors = getThemeColors();

    return new Chart(ctx, {
        type: 'line',
        data: { datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: {
                    display: true,
                    text: title,
                    color: themeColors.text
                },
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        color: themeColors.text
                    }
                }
            },
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'day',
                        displayFormats: {
                            day: 'MMM dd, yyyy'
                        }
                    },
                    title: {
                        display: true,
                        text: 'Time',
                        color: themeColors.text
                    },
                    ticks: {
                        color: themeColors.text
                    },
                    grid: {
                        color: themeColors.grid
                    }
                },
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: yAxisLabel,
                        color: themeColors.text
                    },
                    ticks: {
                        color: themeColors.text
                    },
                    grid: {
                        color: themeColors.grid
                    }
                }
            }
        }
    });
}

/**
 * Map a CSV column to {x, y} points, leaving gaps where the value is missing
 */
function columnPoints(data, column) {
    return data.map(row => {
        const value = parseFloat(row[column]);
        return {
            x: new Date(row.timestamp),
            y: isFinite(value) ? value : null
        };
    });
}

/**
 * Create Wait Time Chart
 *
 * Shows the estimated wait for a new request of each size at each snapshot alongside
 * how long the newest request of that size filled in each batch actually waited.
 *
 * @param {string} canvasId - Canvas element ID
 * @param {string} title - Chart title
 * @param {Array<Object>} data - Time-series data
 * @returns {Chart} Chart.js instance
 */
function createWaitTimeChart(canvasId, title, data) {
    try {
        const datasets = [];

        Object.keys(colors).forEach(size => {
            // Estimated wait for a new request of this size
            datasets.push({
                label: `Estimated ${size}`,
                data: columnPoints(data, `estimated_wait_months_${size.slice(1)}`),
                borderColor: colors[size],
                backgroundColor: colors[size] + '20',
                borderWidth: 3,
                tension: 0.1
            });

            // Observed waits only change when a batch is filled, so draw them as steps
            datasets.push({
                label: `Last ${size} fill waited`,
                data: columnPoints(data, `last_fill_wait_months_${size.slice(1)}`),
                borderColor: colors[size],
                backgroundColor: colors[size] + '20',
                borderDash: [6, 4],
                pointRadius: 0,
                stepped: true
            });
        });

        return createTimeSeriesChart(canvasId, title, datasets, 'Months');
    } catch (error) {
        console.error(`Error creating wait time chart ${canvasId}:`, error);
        throw error;
    }
}

/**
 * Create Time on Waitlist When Filled Chart
 *
 * For each issuance batch, the median wait of requests of each size that were filled,
 * with the middle half (25th-75th percentile) shaded behind it.
 *
 * @param {string} canvasId - Canvas element ID
 * @param {string} title - Chart title
 * @param {Array<Object>} fillData - Rows from fills_by_batch.csv
 * @returns {Chart} Chart.js instance
 */
function createFillWaitChart(canvasId, title, fillData) {
    try {
        const datasets = [];

        Object.keys(colors).forEach(size => {
            const rows = fillData.filter(row => row.size === size.slice(1));
            const points = column => rows.map(row => ({
                x: new Date(row.batch_date),
                y: parseFloat(row[column]),
                row
            }));

            // Middle half as a band: the 75th percentile line fills down to the 25th
            datasets.push({
                label: `${size} 25th percentile`,
                data: points('wait_p25_months'),
                borderColor: 'transparent',
                pointRadius: 0,
                pointHitRadius: 0,
                tension: 0.1
            });
            datasets.push({
                label: `${size} 75th percentile`,
                data: points('wait_p75_months'),
                borderColor: 'transparent',
                backgroundColor: colors[size] + '30',
                pointRadius: 0,
                pointHitRadius: 0,
                fill: '-1',
                tension: 0.1
            });
            datasets.push({
                label: `${size} median`,
                data: points('wait_median_months'),
                borderColor: colors[size],
                backgroundColor: colors[size],
                borderWidth: 2,
                tension: 0.1
            });
        });

        const chart = createTimeSeriesChart(canvasId, title, datasets, 'Months Waited');

        // Show only the median lines in the legend and tooltips, with the batch details
        chart.options.plugins.legend.labels.filter = item => item.text.endsWith('median');
        chart.options.plugins.tooltip = {
            filter: item => item.dataset.label.endsWith('median'),
            callbacks: {
                label: context => {
                    const row = context.raw.row;
                    return `${context.dataset.label}: ${row.wait_median_months} months ` +
                        `(middle half ${row.wait_p25_months}–${row.wait_p75_months}, ${row.filled} filled)`;
                }
            }
        };
        chart.update();
        return chart;
    } catch (error) {
        console.error(`Error creating fill wait chart ${canvasId}:`, error);
        throw error;
    }
}

/**
 * Create Waiting vs Issued Chart
 *
 * Compares address space waiting in line with the average issued per quarter.
 * The ratio of the two is roughly how many quarterly batches it takes to clear the line.
 *
 * @param {string} canvasId - Canvas element ID
 * @param {string} title - Chart title
 * @param {Array<Object>} data - Time-series data
 * @returns {Chart} Chart.js instance
 */
function createQueueSupplyChart(canvasId, title, data) {
    try {
        const datasets = [
            {
                label: 'Waiting',
                data: columnPoints(data, 'queue_24eq'),
                borderColor: colors['/22'],
                backgroundColor: colors['/22'] + '20',
                tension: 0.1
            },
            {
                label: 'Issued per quarter (2-year average)',
                data: columnPoints(data, 'supply_24eq_per_quarter'),
                borderColor: colors['/24'],
                backgroundColor: colors['/24'] + '20',
                tension: 0.1
            }
        ];

        return createTimeSeriesChart(canvasId, title, datasets, '/24 Equivalents');
    } catch (error) {
        console.error(`Error creating queue/supply chart ${canvasId}:`, error);
        throw error;
    }
}

/**
 * Create Address Space Issued Chart
 *
 * Stacked bar chart of address space ARIN issued to the waitlist each quarter,
 * broken down by the size of block it came from.
 *
 * @param {string} canvasId - Canvas element ID
 * @param {string} title - Chart title
 * @param {Array<Object>} issuedData - Rows from issued_by_quarter.csv
 * @returns {Chart} Chart.js instance
 */
function createIssuedChart(canvasId, title, issuedData) {
    try {
        const ctx = document.getElementById(canvasId).getContext('2d');
        const themeColors = getThemeColors();

        const sources = [
            { label: 'From /21 and larger blocks', column: 'eq24_from_larger', color: '#ffa500' },
            { label: 'From /22 blocks', column: 'eq24_from_22', color: colors['/22'] },
            { label: 'From /23 blocks', column: 'eq24_from_23', color: colors['/23'] },
            { label: 'From /24 blocks', column: 'eq24_from_24', color: colors['/24'] }
        ];

        return new Chart(ctx, {
            type: 'bar',
            data: {
                labels: issuedData.map(row => row.quarter.replace('Q', ' Q')),  // '2026Q3' -> '2026 Q3'
                datasets: sources.map(source => ({
                    label: source.label,
                    data: issuedData.map(row => parseInt(row[source.column]) || 0),
                    backgroundColor: source.color + 'b3',
                    borderColor: source.color,
                    borderWidth: 1
                }))
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: title,
                        color: themeColors.text
                    },
                    legend: {
                        display: true,
                        labels: {
                            color: themeColors.text
                        }
                    }
                },
                scales: {
                    x: {
                        stacked: true,
                        title: {
                            display: true,
                            text: 'Quarter',
                            color: themeColors.text
                        },
                        ticks: {
                            color: themeColors.text
                        },
                        grid: {
                            color: themeColors.grid
                        }
                    },
                    y: {
                        stacked: true,
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: '/24 Equivalents Issued',
                            color: themeColors.text
                        },
                        ticks: {
                            color: themeColors.text
                        },
                        grid: {
                            color: themeColors.grid
                        }
                    }
                }
            }
        });
    } catch (error) {
        console.error(`Error creating issued chart ${canvasId}:`, error);
        throw error;
    }
}

// Function to format numbers with commas
function formatNumber(num) {
    if (num === null || num === undefined || isNaN(num)) return '-';
    return parseFloat(num).toLocaleString();
}

// Function to format months with 1 decimal place
function formatMonths(months) {
    if (months === null || months === undefined || isNaN(months)) return '-';
    if (months === Infinity) return '∞';
    return parseFloat(months).toFixed(1) + ' months';
}

// Function to format a YYYY-MM-DD date (dates are UTC, so format in UTC to avoid shifting a day)
function formatDate(dateStr) {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        timeZone: 'UTC'
    });
}

// Function to format percentages
function formatPercentage(value, total) {
    if (total === 0 || isNaN(value) || isNaN(total)) return '0.0%';
    return ((value / total) * 100).toFixed(1) + '%';
}

// Function to calculate trend indicator
function getTrendIndicator(current, previous, reverse = false) {
    if (previous === null || previous === undefined || current === previous) {
        return '<span class="trend-indicator trend-stable">●</span>';
    }
    const isUp = current > previous;
    const trend = reverse ? !isUp : isUp;
    const arrow = trend ? '↗' : '↘';
    const className = trend ? 'trend-up' : 'trend-down';
    return `<span class="trend-indicator ${className}">${arrow}</span>`;
}

// Function to calculate block efficiency (IPs per year wait time)
function calculateBlockEfficiency(ips, waitYears) {
    if (!isFinite(waitYears) || waitYears <= 0) return 0;
    return ips / waitYears;
}

// Function to calculate and display statistics
/**
 * Update all statistics cards with latest data
 *
 * Extracts the most recent data point from the time-series and updates
 * all the statistics cards displayed at the top of the dashboard. This includes
 * current waitlist size, recent activity, flexibility metrics, and age statistics.
 *
 * @param {Array<Object>} data - Parsed CSV data (sorted chronologically)
 */
function updateStatistics(data) {
    if (data.length === 0) return;

    try {
        // Get the most recent data point and previous for trends
        const latest = data[data.length - 1];
        const previous = data.length > 1 ? data[data.length - 2] : null;

        // Current waitlist counts
        const req22 = parseInt(latest.requests_22) || 0;
        const req23 = parseInt(latest.requests_23) || 0;
        const req24 = parseInt(latest.requests_24) || 0;
        const totalReq = parseInt(latest.total_requests) || 0;

        // Estimated wait for a new request of each size (simulated future batches)
        const estimatedWait22 = parseFloat(latest.estimated_wait_months_22);
        const estimatedWait23 = parseFloat(latest.estimated_wait_months_23);
        const estimatedWait24 = parseFloat(latest.estimated_wait_months_24);
        const supply24eq = parseFloat(latest.supply_24eq_per_quarter) || 0;

        // How long the newest request filled in the latest batch had waited, by size
        const lastFillWait22 = parseFloat(latest.last_fill_wait_months_22);
        const lastFillWait23 = parseFloat(latest.last_fill_wait_months_23);
        const lastFillWait24 = parseFloat(latest.last_fill_wait_months_24);

        // Calculated statistics
        const total24Equiv = (req22 * 4) + (req23 * 2) + req24;
        const totalIPs = (req22 * 1024) + (req23 * 512) + (req24 * 256);
        const totalRequests = req22 + req23 + req24;

        // Block efficiency calculations (IPs per year of estimated wait)
        const eff22 = calculateBlockEfficiency(1024, estimatedWait22 / 12);
        const eff23 = calculateBlockEfficiency(512, estimatedWait23 / 12);
        const eff24 = calculateBlockEfficiency(256, estimatedWait24 / 12);

        const efficiencies = [
            { type: '/22', efficiency: eff22, ips: 1024 },
            { type: '/23', efficiency: eff23, ips: 512 },
            { type: '/24', efficiency: eff24, ips: 256 }
        ].filter(e => e.efficiency > 0).sort((a, b) => b.efficiency - a.efficiency);

        const mostEfficient = efficiencies[0];
        const leastEfficient = efficiencies[efficiencies.length - 1];

        // Historical analysis
        const allTotals = data.map(d => parseInt(d.total_requests) || 0);
        const peakTotal = Math.max(...allTotals);
        const minTotal = Math.min(...allTotals);

        // Net change rate calculation (requests per time period)
        let netChangeRate = 0;
        let changeText = 'No data';
        if (data.length >= 2) {
            const oldestTotal = parseInt(data[0].total_requests) || 0;
            const latestTotal = parseInt(latest.total_requests) || 0;
            const totalChange = latestTotal - oldestTotal;

            // Calculate time span in years
            const oldestDate = new Date(data[0].timestamp);
            const latestDate = new Date(latest.timestamp);
            const yearsSpan = (latestDate - oldestDate) / (1000 * 60 * 60 * 24 * 365.25);

            if (yearsSpan > 0) {
                netChangeRate = totalChange / yearsSpan;
                const sign = netChangeRate >= 0 ? '+' : '';
                changeText = `${sign}${Math.round(netChangeRate)} req/year`;
            }
        }

        // Supply vs new demand: address space issued per year compared with address
        // space requested by new requests over the last year (both in /24 equivalents).
        // Below 100% means the line grows and waits get longer.
        const latestTime = new Date(latest.timestamp);
        const yearAgo = latestTime - (1000 * 60 * 60 * 24 * 365.25);
        const lastYearRows = data.slice(1).filter(row => new Date(row.timestamp) > yearAgo);
        const added24eqLastYear = lastYearRows.reduce((sum, row) =>
            sum + (parseInt(row.added_22) || 0) * 4 + (parseInt(row.added_23) || 0) * 2 + (parseInt(row.added_24) || 0), 0);
        let efficiencyRatio = 'No trend data';
        if (lastYearRows.length > 0 && added24eqLastYear > 0) {
            // Scale to a full year if the data covers less than that
            const coveredYears = (latestTime - new Date(data[data.length - lastYearRows.length - 1].timestamp)) /
                (1000 * 60 * 60 * 24 * 365.25);
            const addedPerYear = added24eqLastYear / Math.min(Math.max(coveredYears, 0.01), 1);
            const ratio = (supply24eq * 4) / addedPerYear;
            efficiencyRatio = `${(ratio * 100).toFixed(0)}% of new demand`;
        }

        // Previous data for trends
        const prevTotal = previous ? parseInt(previous.total_requests) || 0 : null;

        // Market share calculations
        const share22 = formatPercentage(req22, totalRequests);
        const share23 = formatPercentage(req23, totalRequests);
        const share24 = formatPercentage(req24, totalRequests);

        // Find largest demand category
        const demands = [
            { type: '/22', count: req22, share: share22 },
            { type: '/23', count: req23, share: share23 },
            { type: '/24', count: req24, share: share24 }
        ].sort((a, b) => b.count - a.count);

        const largestDemand = demands[0];

        // Update current waitlist
        document.getElementById('current-22').textContent = formatNumber(req22);
        document.getElementById('current-23').textContent = formatNumber(req23);
        document.getElementById('current-24').textContent = formatNumber(req24);
        document.getElementById('total-requests').textContent = formatNumber(totalReq);

        // Update estimated wait
        // Average across historical scenarios, with the typical (25th-75th percentile) range
        [['22', estimatedWait22], ['23', estimatedWait23], ['24', estimatedWait24]].forEach(([size, waited]) => {
            const low = parseFloat(latest[`estimated_wait_p25_months_${size}`]);
            const high = parseFloat(latest[`estimated_wait_p75_months_${size}`]);
            const range = isFinite(low) && isFinite(high) ? ` (${Math.round(low)}–${Math.round(high)})` : '';
            document.getElementById(`estimated-wait-${size}`).textContent = formatMonths(waited) + range;
        });
        document.getElementById('supply-24eq').textContent = formatNumber(supply24eq);

        // Update most recent fills (a size not filled in the latest batch shows its own batch date)
        const lastFillDates = [latest.last_fill_date_22, latest.last_fill_date_23, latest.last_fill_date_24]
            .filter(date => date).sort();
        const latestBatch = lastFillDates[lastFillDates.length - 1];
        [['22', lastFillWait22], ['23', lastFillWait23], ['24', lastFillWait24]].forEach(([size, waited]) => {
            const date = latest[`last_fill_date_${size}`];
            const suffix = date && date !== latestBatch ? ` (${formatDate(date)})` : '';
            document.getElementById(`last-fill-${size}`).textContent = formatMonths(waited) + suffix;
        });
        document.getElementById('last-fill-date').textContent = formatDate(latestBatch);

        // Update network analysis
        document.getElementById('total-24-equiv').textContent = formatNumber(total24Equiv);
        document.getElementById('total-ips').textContent = formatNumber(totalIPs);

        // Update efficiency analysis
        if (mostEfficient) {
            document.getElementById('most-efficient').textContent =
                `${mostEfficient.type} (${Math.round(mostEfficient.efficiency)} IPs/yr)`;
        }
        if (leastEfficient) {
            document.getElementById('least-efficient').textContent =
                `${leastEfficient.type} (${Math.round(leastEfficient.efficiency)} IPs/yr)`;
        }

        // Update historical context with trends
        const totalTrendHtml = formatNumber(totalReq) + getTrendIndicator(totalReq, prevTotal, true);
        document.getElementById('total-trend').innerHTML = totalTrendHtml;

        document.getElementById('peak-total').textContent =
            `${formatNumber(peakTotal)} (${peakTotal === totalReq ? 'current' : 'all-time'})`;

        document.getElementById('net-change').textContent = changeText;
        document.getElementById('clearing-efficiency').textContent = efficiencyRatio;

        // Update market share statistics
        document.getElementById('market-22-requests').textContent = share22;
        document.getElementById('market-23-requests').textContent = share23;
        document.getElementById('market-24-requests').textContent = share24;
        document.getElementById('largest-demand').textContent =
            `${largestDemand.type} (${largestDemand.share})`;

        // Update recent activity statistics
        const recentAdded = parseInt(latest.added_total) || 0;
        const recentRemoved = parseInt(latest.removed_total) || 0;
        const recentNetChange = parseInt(latest.net_change) || 0;

        document.getElementById('recent-added').textContent = `+${formatNumber(recentAdded)}`;
        document.getElementById('recent-removed').textContent = formatNumber(recentRemoved);

        // Net change with sign and color
        const netChangeSign = recentNetChange >= 0 ? '+' : '';
        const netChangeClass = recentNetChange > 0 ? 'trend-up' : (recentNetChange < 0 ? 'trend-down' : 'trend-stable');
        const netChangeEl = document.getElementById('recent-net-change');
        netChangeEl.textContent = `${netChangeSign}${formatNumber(recentNetChange)}`;
        netChangeEl.className = `stat-value ${netChangeClass}`;

        // Turnover rate (% of waitlist that changed)
        const turnoverRate = totalReq > 0 ? ((recentAdded + recentRemoved) / totalReq) * 100 : 0;
        document.getElementById('turnover-rate').textContent = `${turnoverRate.toFixed(1)}%`;

        // Update flexibility statistics
        const flexExact = parseInt(latest.exact_requests) || 0;
        const flexFlexible = parseInt(latest.flexible_requests) || 0;
        const flexAvg = parseFloat(latest.avg_flexibility) || 0;
        const flexTotal = flexExact + flexFlexible;
        const flexRatio = flexTotal > 0 ? (flexFlexible / flexTotal) * 100 : 0;

        document.getElementById('flex-exact').textContent = formatNumber(flexExact);
        document.getElementById('flex-flexible').textContent = formatNumber(flexFlexible);
        document.getElementById('flex-avg').textContent = flexAvg.toFixed(2) + ' CIDR levels';
        document.getElementById('flex-ratio').textContent = flexRatio.toFixed(1) + '%';

        // Show the statistics section
        document.getElementById('statistics').style.display = 'block';

    } catch (error) {
        console.error('Error updating statistics:', error);
        // Hide statistics section if there's an error
        document.getElementById('statistics').style.display = 'none';
    }
}

// Function to create activity chart (added vs removed)
// ============================================================================
// === SPECIALIZED CHART FUNCTIONS ===
// ============================================================================
// Each function below creates a specific type of chart with custom configuration

/**
 * Create Request Activity Chart (Added vs Removed)
 *
 * Displays a line chart comparing requests added to the waitlist versus
 * requests removed (fulfilled or cancelled) over time. Helps visualize
 * request churn and identify periods of high activity.
 *
 * Features:
 * - Two lines: "Added" (new requests) and "Removed" (fulfilled/cancelled)
 * - Different colors to distinguish added vs removed
 * - Filters out first data point (no previous snapshot to compare)
 *
 * @param {string} canvasId - Canvas element ID
 * @param {string} title - Chart title
 * @param {Array<Object>} data - Time-series data
 * @returns {Chart} Chart.js instance
 */
function createActivityChart(canvasId, title, data) {
    try {
        const ctx = document.getElementById(canvasId).getContext('2d');
        const themeColors = getThemeColors();

        // Filter out first data point (has no previous to compare against)
        const filteredData = data.slice(1);

        // Create datasets for added and removed requests
        const addedData = filteredData.map(row => ({
            x: new Date(row.timestamp),
            y: parseInt(row.added_total) || 0
        }));

        const removedData = filteredData.map(row => ({
            x: new Date(row.timestamp),
            y: parseInt(row.removed_total) || 0
        }));

        return new Chart(ctx, {
            type: 'line',
            data: {
                datasets: [
                    {
                        label: 'Requests Added',
                        data: addedData,
                        borderColor: '#4ecdc4',
                        backgroundColor: '#4ecdc4' + '20',
                        tension: 0.1,
                        fill: true
                    },
                    {
                        label: 'Requests Removed',
                        data: removedData,
                        borderColor: '#ff6b6b',
                        backgroundColor: '#ff6b6b' + '20',
                        tension: 0.1,
                        fill: true
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: title,
                        color: themeColors.text
                    },
                    legend: {
                        display: true,
                        position: 'top',
                        labels: {
                            color: themeColors.text
                        }
                    }
                },
                scales: {
                    x: {
                        type: 'time',
                        time: {
                            unit: 'day',
                            displayFormats: {
                                day: 'MMM dd, yyyy'
                            }
                        },
                        title: {
                            display: true,
                            text: 'Time',
                            color: themeColors.text
                        },
                        ticks: {
                            color: themeColors.text
                        },
                        grid: {
                            color: themeColors.grid
                        }
                    },
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Number of Requests',
                            color: themeColors.text
                        },
                        ticks: {
                            color: themeColors.text
                        },
                        grid: {
                            color: themeColors.grid
                        }
                    }
                }
            }
        });
    } catch (error) {
        console.error(`Error creating activity chart ${canvasId}:`, error);
        throw error;
    }
}

// Function to create efficiency ratio chart
function createEfficiencyRatioChart(canvasId, title, data) {
    try {
        const ctx = document.getElementById(canvasId).getContext('2d');
        const themeColors = getThemeColors();

        // Filter out first data point (no previous to compare)
        const filteredData = data.slice(1);

        // Calculate efficiency ratio for each data point
        const ratioData = filteredData.map(row => {
            const added = parseInt(row.added_total) || 0;
            const removed = parseInt(row.removed_total) || 0;

            // Calculate ratio (removed / added)
            // If added is 0, treat as infinity or special case
            const ratio = added > 0 ? removed / added : (removed > 0 ? 999 : 1.0);

            return {
                x: new Date(row.timestamp),
                y: ratio
            };
        });

        return new Chart(ctx, {
            type: 'line',
            data: {
                datasets: [
                    {
                        label: 'Efficiency Ratio',
                        data: ratioData,
                        borderColor: '#ffa500',
                        backgroundColor: 'rgba(255, 165, 0, 0.1)',
                        tension: 0.1,
                        fill: true,
                        borderWidth: 2
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: title,
                        color: themeColors.text
                    },
                    legend: {
                        display: true,
                        position: 'top',
                        labels: {
                            color: themeColors.text
                        }
                    },
                    annotation: {
                        annotations: {
                            line1: {
                                type: 'line',
                                yMin: 1.0,
                                yMax: 1.0,
                                borderColor: '#4ecdc4',
                                borderWidth: 2,
                                borderDash: [5, 5],
                                label: {
                                    display: true,
                                    content: 'Break-even (1.0)',
                                    position: 'end',
                                    color: themeColors.text
                                }
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        type: 'time',
                        time: {
                            unit: 'day',
                            displayFormats: {
                                day: 'MMM dd, yyyy'
                            }
                        },
                        title: {
                            display: true,
                            text: 'Time',
                            color: themeColors.text
                        },
                        ticks: {
                            color: themeColors.text
                        },
                        grid: {
                            color: themeColors.grid
                        }
                    },
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Ratio (>1.0 = sustainable, <1.0 = growing backlog)',
                            color: themeColors.text
                        },
                        ticks: {
                            color: themeColors.text
                        },
                        grid: {
                            color: themeColors.grid
                        }
                    }
                }
            }
        });
    } catch (error) {
        console.error(`Error creating efficiency ratio chart ${canvasId}:`, error);
        throw error;
    }
}

// Function to create block size competition chart
function createBlockSizeCompetitionChart(canvasId, title, data) {
    try {
        const ctx = document.getElementById(canvasId).getContext('2d');
        const themeColors = getThemeColors();

        // Filter out first data point
        const filteredData = data.slice(1);

        // Create datasets for net change by block size
        const netChange22Data = filteredData.map(row => {
            const added = parseInt(row.added_22) || 0;
            const removed = parseInt(row.removed_22) || 0;
            return {
                x: new Date(row.timestamp),
                y: added - removed
            };
        });

        const netChange23Data = filteredData.map(row => {
            const added = parseInt(row.added_23) || 0;
            const removed = parseInt(row.removed_23) || 0;
            return {
                x: new Date(row.timestamp),
                y: added - removed
            };
        });

        const netChange24Data = filteredData.map(row => {
            const added = parseInt(row.added_24) || 0;
            const removed = parseInt(row.removed_24) || 0;
            return {
                x: new Date(row.timestamp),
                y: added - removed
            };
        });

        return new Chart(ctx, {
            type: 'line',
            data: {
                datasets: [
                    {
                        label: '/22 Net Change',
                        data: netChange22Data,
                        borderColor: colors['/22'],
                        backgroundColor: colors['/22'] + '20',
                        tension: 0.1,
                        fill: false,
                        borderWidth: 2
                    },
                    {
                        label: '/23 Net Change',
                        data: netChange23Data,
                        borderColor: colors['/23'],
                        backgroundColor: colors['/23'] + '20',
                        tension: 0.1,
                        fill: false,
                        borderWidth: 2
                    },
                    {
                        label: '/24 Net Change',
                        data: netChange24Data,
                        borderColor: colors['/24'],
                        backgroundColor: colors['/24'] + '20',
                        tension: 0.1,
                        fill: false,
                        borderWidth: 2
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: title,
                        color: themeColors.text
                    },
                    legend: {
                        display: true,
                        position: 'top',
                        labels: {
                            color: themeColors.text
                        }
                    }
                },
                scales: {
                    x: {
                        type: 'time',
                        time: {
                            unit: 'day',
                            displayFormats: {
                                day: 'MMM dd, yyyy'
                            }
                        },
                        title: {
                            display: true,
                            text: 'Time',
                            color: themeColors.text
                        },
                        ticks: {
                            color: themeColors.text
                        },
                        grid: {
                            color: themeColors.grid
                        }
                    },
                    y: {
                        title: {
                            display: true,
                            text: 'Net Change (Added - Removed)',
                            color: themeColors.text
                        },
                        ticks: {
                            color: themeColors.text
                        },
                        grid: {
                            color: themeColors.grid
                        }
                    }
                }
            }
        });
    } catch (error) {
        console.error(`Error creating block size competition chart ${canvasId}:`, error);
        throw error;
    }
}

// Function to create flexibility distribution pie chart
function createFlexibilityDistributionChart(canvasId, title, data) {
    try {
        const ctx = document.getElementById(canvasId).getContext('2d');
        const themeColors = getThemeColors();

        // Get the most recent data point
        const latest = data[data.length - 1];
        const flexibleRequests = parseInt(latest.flexible_requests) || 0;
        const exactRequests = parseInt(latest.exact_requests) || 0;

        return new Chart(ctx, {
            type: 'pie',
            data: {
                labels: ['Exact Size Requests', 'Flexible Range Requests'],
                datasets: [{
                    data: [exactRequests, flexibleRequests],
                    backgroundColor: [
                        'rgba(255, 99, 132, 0.7)',
                        'rgba(54, 162, 235, 0.7)'
                    ],
                    borderColor: [
                        'rgba(255, 99, 132, 1)',
                        'rgba(54, 162, 235, 1)'
                    ],
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: title,
                        color: themeColors.text
                    },
                    legend: {
                        display: true,
                        position: 'bottom',
                        labels: {
                            color: themeColors.text,
                            generateLabels: function(chart) {
                                const data = chart.data;
                                const total = exactRequests + flexibleRequests;
                                return data.labels.map((label, i) => {
                                    const value = data.datasets[0].data[i];
                                    const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                                    return {
                                        text: `${label}: ${value} (${percentage}%)`,
                                        fillStyle: data.datasets[0].backgroundColor[i],
                                        hidden: false,
                                        index: i
                                    };
                                });
                            }
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const label = context.label || '';
                                const value = context.parsed;
                                const total = exactRequests + flexibleRequests;
                                const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                                return `${label}: ${value} (${percentage}%)`;
                            }
                        }
                    }
                }
            }
        });
    } catch (error) {
        console.error(`Error creating flexibility distribution chart ${canvasId}:`, error);
        throw error;
    }
}

// Function to create age distribution bar chart
function createAgeDistributionChart(canvasId, title, data) {
    try {
        const ctx = document.getElementById(canvasId).getContext('2d');
        const themeColors = getThemeColors();

        // Get the most recent data point
        const latest = data[data.length - 1];

        // Parse age distribution by size
        const age0_3_22 = parseInt(latest.age_0_3mo_22) || 0;
        const age0_3_23 = parseInt(latest.age_0_3mo_23) || 0;
        const age0_3_24 = parseInt(latest.age_0_3mo_24) || 0;

        const age3_6_22 = parseInt(latest.age_3_6mo_22) || 0;
        const age3_6_23 = parseInt(latest.age_3_6mo_23) || 0;
        const age3_6_24 = parseInt(latest.age_3_6mo_24) || 0;

        const age6_12_22 = parseInt(latest.age_6_12mo_22) || 0;
        const age6_12_23 = parseInt(latest.age_6_12mo_23) || 0;
        const age6_12_24 = parseInt(latest.age_6_12mo_24) || 0;

        const age12_24_22 = parseInt(latest.age_12_24mo_22) || 0;
        const age12_24_23 = parseInt(latest.age_12_24mo_23) || 0;
        const age12_24_24 = parseInt(latest.age_12_24mo_24) || 0;

        const age24plus_22 = parseInt(latest.age_24plus_22) || 0;
        const age24plus_23 = parseInt(latest.age_24plus_23) || 0;
        const age24plus_24 = parseInt(latest.age_24plus_24) || 0;

        return new Chart(ctx, {
            type: 'bar',
            data: {
                labels: ['0-3 months', '3-6 months', '6-12 months', '1-2 years', '2+ years'],
                datasets: [
                    {
                        label: '/22 Requests',
                        data: [age0_3_22, age3_6_22, age6_12_22, age12_24_22, age24plus_22],
                        backgroundColor: 'rgba(255, 99, 132, 0.7)',
                        borderColor: 'rgba(255, 99, 132, 1)',
                        borderWidth: 1
                    },
                    {
                        label: '/23 Requests',
                        data: [age0_3_23, age3_6_23, age6_12_23, age12_24_23, age24plus_23],
                        backgroundColor: 'rgba(54, 162, 235, 0.7)',
                        borderColor: 'rgba(54, 162, 235, 1)',
                        borderWidth: 1
                    },
                    {
                        label: '/24 Requests',
                        data: [age0_3_24, age3_6_24, age6_12_24, age12_24_24, age24plus_24],
                        backgroundColor: 'rgba(75, 192, 192, 0.7)',
                        borderColor: 'rgba(75, 192, 192, 1)',
                        borderWidth: 1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: title,
                        color: themeColors.text
                    },
                    legend: {
                        display: true,
                        labels: {
                            color: themeColors.text
                        }
                    },
                    tooltip: {
                        callbacks: {
                            afterLabel: function(context) {
                                // Calculate total for this age range across all sizes
                                const datasetIndex = context.datasetIndex;
                                const ageIndex = context.dataIndex;
                                let total = 0;
                                context.chart.data.datasets.forEach(dataset => {
                                    total += dataset.data[ageIndex] || 0;
                                });
                                const percentage = total > 0 ? ((context.parsed.y / total) * 100).toFixed(1) : 0;
                                return `${percentage}% of age range`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        stacked: true,
                        title: {
                            display: true,
                            text: 'Age Range',
                            color: themeColors.text
                        },
                        ticks: {
                            color: themeColors.text
                        },
                        grid: {
                            color: themeColors.grid
                        }
                    },
                    y: {
                        stacked: true,
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Number of Requests',
                            color: themeColors.text
                        },
                        ticks: {
                            color: themeColors.text
                        },
                        grid: {
                            color: themeColors.grid
                        }
                    }
                }
            }
        });
    } catch (error) {
        console.error(`Error creating age distribution chart ${canvasId}:`, error);
        throw error;
    }
}

// Function to update last updated timestamp
function updateLastUpdated(data) {
    if (data.length === 0) return;

    try {
        // Find the most recent timestamp (data is already sorted by timestamp)
        const mostRecentEntry = data[data.length - 1];
        const timestamp = new Date(mostRecentEntry.timestamp);

        // Format in human-readable format using toLocaleDateString for date only
        const formattedTime = timestamp.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'long',
            day: 'numeric'
        });

        // Update the DOM
        document.getElementById('lastUpdatedTime').textContent = formattedTime;
        document.getElementById('lastUpdated').style.display = 'block';
    } catch (error) {
        console.error('Error updating last updated timestamp:', error);
        // Hide the last updated element if there's an error
        document.getElementById('lastUpdated').style.display = 'none';
    }
}

// ============================================================================
// === MAIN DATA LOADING AND INITIALIZATION ===
// ============================================================================

/**
 * Load CSV data and initialize all charts and statistics
 *
 * This is the main entry point for the dashboard. It:
 * 1. Fetches the CSV file containing time-series data
 * 2. Parses the CSV into structured data
 * 3. Updates all statistics cards
 * 4. Creates all 10 charts
 * 5. Handles loading states and errors
 *
 * Called automatically when the DOM is ready.
 */
async function loadData() {
    try {
        // === Fetch CSV Data ===
        // Load the time-series CSV file (generated by process.py)
        const response = await fetch('waitlist_data.csv');
        if (!response.ok) {
            throw new Error('Failed to load CSV file');
        }

        // Parse CSV text into structured data
        const csvText = await response.text();
        const data = parseCSV(csvText);

        // Validate we got data
        if (data.length === 0) {
            throw new Error('No data found in CSV file');
        }

        // Load per-quarter issued space and per-batch fill waits (optional - only their
        // charts are skipped if missing)
        const loadOptionalCSV = async file => {
            try {
                const optionalResponse = await fetch(file);
                return optionalResponse.ok ? parseCSV(await optionalResponse.text()) : [];
            } catch (error) {
                console.error(`Error loading ${file}:`, error);
                return [];
            }
        };
        const issuedData = await loadOptionalCSV('issued_by_quarter.csv');
        const fillData = await loadOptionalCSV('fills_by_batch.csv');

        // === Update UI State ===
        // Hide loading spinner, show charts
        document.getElementById('loading').style.display = 'none';
        document.getElementById('charts').style.display = 'block';

        // Update "Last Updated" timestamp
        updateLastUpdated(data);

        // Update statistics cards with latest values
        updateStatistics(data);

        // === Create All Charts ===
        // Basic line charts showing trends over time
        // Chart 1: Waitlist Size - Shows total pending requests by block size over time
        createChart('waitlistChart', 'Current Waitlist Size Over Time', data, {
            '/22': 'requests_22',
            '/23': 'requests_23',
            '/24': 'requests_24'
        }, 'Number of Requests');

        // Chart 2: Wait Time - Estimated wait vs how long recent fills actually waited
        createWaitTimeChart('waitTimeChart', 'Estimated vs Observed Wait', data);

        // Chart 3: Time on Waitlist When Filled - Actual waits per batch and size
        if (fillData.length > 0) {
            createFillWaitChart('fillWaitChart', 'Time on Waitlist When Filled', fillData);
        }

        // Chart 4: Address Space Issued - Supply per quarter by source block size
        if (issuedData.length > 0) {
            createIssuedChart('historicalChart', 'Address Space Issued Per Quarter', issuedData);
        }

        // Chart 5: Waiting vs Issued - Queue size compared with average supply
        createQueueSupplyChart('processedChart', 'Waiting vs Issued Per Quarter', data);

        // Chart 6: Request Activity - Added vs removed requests (churn tracking)
        createActivityChart('activityChart', 'Request Activity Over Time', data);

        // Chart 7: Efficiency Ratio - How effectively the waitlist is clearing (removed/added)
        createEfficiencyRatioChart('efficiencyRatioChart', 'Clearing Efficiency Over Time', data);

        // Chart 8: Block Size Competition - Net change by CIDR size
        createBlockSizeCompetitionChart('blockSizeCompetitionChart', 'Net Change by Block Size', data);

        // Chart 9: Flexibility Distribution - Pie chart: exact vs flexible requesters
        createFlexibilityDistributionChart('flexibilityDistributionChart', 'Request Flexibility Distribution', data);

        // Chart 10: Age Distribution - Stacked bar chart showing request ages by CIDR size
        createAgeDistributionChart('ageDistributionChart', 'Current Request Age Distribution', data);

    } catch (error) {
        // Handle any errors during data loading or chart creation
        console.error('Error loading data:', error);
        document.getElementById('loading').style.display = 'none';
        document.getElementById('error').style.display = 'block';
    }
}

// ============================================================================
// === INITIALIZATION ===
// ============================================================================

/**
 * Initialize dashboard when DOM is ready
 *
 * Waits for the HTML document to fully load, then triggers data loading
 * and chart creation. This ensures all canvas elements exist before we
 * try to create charts on them.
 */
document.addEventListener('DOMContentLoaded', loadData);

// End of dashboard JavaScript
