#!/usr/bin/env python3
"""
DSBD Flight Tracker - Prometheus Metrics Reader

Query Prometheus for microservice metrics, compute statistics,
and visualize performance over time.

Requirements:
    pip install requests matplotlib
"""

import requests
import time
from datetime import datetime
import matplotlib.pyplot as plt
import argparse


# ----------------------- CONFIG -----------------------

# Prometheus base URL (adjust for docker-compose or k8s port-forward)
PROMETHEUS_BASE_URL = "http://localhost:9090"

# Time window: last hour by default
DEFAULT_RANGE_HOURS = 1

# Resolution of query_range data (seconds)
STEP_SECONDS = 15

# Output directory for charts
OUTPUT_DIR = "metrics_output"


# ----------------------- PROMETHEUS CLIENT -----------------------

def prom_query_range(query: str, start: float, end: float, step: float):
    """
    Perform a Prometheus range query and return a list of (timestamp, value) tuples.
    All timestamps are returned as float (unix seconds), values as float.

    If no data is returned, an empty list is returned.
    """
    url = f"{PROMETHEUS_BASE_URL}/api/v1/query_range"
    params = {
        "query": query,
        "start": start,
        "end": end,
        "step": step,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()

        data = resp.json()
        if data.get("status") != "success":
            print(f"Warning: Prometheus query failed: {data}")
            return []

        result = data["data"]["result"]
        if not result:
            return []

        # Process all time-series
        all_values = []
        for series in result:
            values = series.get("values", [])
            for ts_str, val_str in values:
                ts = float(ts_str)
                try:
                    val = float(val_str)
                except ValueError:
                    continue
                all_values.append((ts, val))

        return all_values
    except Exception as e:
        print(f"Error querying Prometheus: {e}")
        return []


def prom_query_instant(query: str):
    """
    Perform an instant query and return the current value.
    """
    url = f"{PROMETHEUS_BASE_URL}/api/v1/query"
    params = {"query": query}

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()

        data = resp.json()
        if data.get("status") != "success":
            return None

        result = data["data"]["result"]
        if not result:
            return None

        # Return first result value
        return float(result[0]["value"][1])
    except Exception as e:
        print(f"Error querying Prometheus: {e}")
        return None


# ----------------------- METRICS ANALYSIS -----------------------

def analyze_user_manager_metrics(hours=1):
    """Analyze UserManager metrics: request count and response time."""
    end_ts = time.time()
    start_ts = end_ts - hours * 3600

    print(f"\n{'='*60}")
    print("USER MANAGER METRICS")
    print(f"{'='*60}")

    # Total requests
    total_requests_query = 'sum(user_manager_requests_total)'
    total = prom_query_instant(total_requests_query)
    if total is not None:
        print(f"Total requests (all time): {int(total)}")

    # Response time over time
    response_time_query = 'user_manager_response_time_seconds'
    response_times = prom_query_range(response_time_query, start_ts, end_ts, STEP_SECONDS)

    if response_times:
        times = [datetime.fromtimestamp(ts) for ts, _ in response_times]
        values = [v for _, v in response_times]

        avg_response = sum(values) / len(values)
        max_response = max(values)
        min_response = min(values)

        print(f"\nResponse Time Statistics (last {hours}h):")
        print(f"  Average: {avg_response:.4f}s")
        print(f"  Min: {min_response:.4f}s")
        print(f"  Max: {max_response:.4f}s")

        # Plot response time
        plt.figure(figsize=(12, 6))
        plt.plot(times, values, label="Response Time", marker='o', markersize=3)
        plt.axhline(y=avg_response, color='r', linestyle='--', label=f'Average ({avg_response:.4f}s)')
        plt.xlabel("Time")
        plt.ylabel("Response Time (seconds)")
        plt.title(f"UserManager Response Time - Last {hours} Hour(s)")
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        
        import os
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        output_file = f"{OUTPUT_DIR}/user_manager_response_time_{hours}h.png"
        plt.savefig(output_file, dpi=150)
        print(f"\nSaved chart: {output_file}")
        plt.close()
    else:
        print("No response time data available")


def analyze_data_collector_metrics(hours=1):
    """Analyze DataCollector metrics: request count and OpenSky API response time."""
    end_ts = time.time()
    start_ts = end_ts - hours * 3600

    print(f"\n{'='*60}")
    print("DATA COLLECTOR METRICS")
    print(f"{'='*60}")

    # Total requests
    total_requests_query = 'sum(data_collector_requests_total)'
    total = prom_query_instant(total_requests_query)
    if total is not None:
        print(f"Total requests (all time): {int(total)}")

    # OpenSky API response time
    opensky_time_query = 'data_collector_opensky_response_time_seconds'
    opensky_times = prom_query_range(opensky_time_query, start_ts, end_ts, STEP_SECONDS)

    if opensky_times:
        times = [datetime.fromtimestamp(ts) for ts, _ in opensky_times]
        values = [v for _, v in opensky_times]

        avg_response = sum(values) / len(values)
        max_response = max(values)
        min_response = min(values)

        print(f"\nOpenSky API Response Time Statistics (last {hours}h):")
        print(f"  Average: {avg_response:.4f}s")
        print(f"  Min: {min_response:.4f}s")
        print(f"  Max: {max_response:.4f}s")

        # Plot OpenSky response time
        plt.figure(figsize=(12, 6))
        plt.plot(times, values, label="OpenSky API Response Time", marker='o', markersize=3, color='green')
        plt.axhline(y=avg_response, color='r', linestyle='--', label=f'Average ({avg_response:.4f}s)')
        plt.xlabel("Time")
        plt.ylabel("Response Time (seconds)")
        plt.title(f"DataCollector OpenSky API Response Time - Last {hours} Hour(s)")
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        
        import os
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        output_file = f"{OUTPUT_DIR}/data_collector_opensky_time_{hours}h.png"
        plt.savefig(output_file, dpi=150)
        print(f"\nSaved chart: {output_file}")
        plt.close()
    else:
        print("No OpenSky API response time data available")


def analyze_request_rates(hours=1):
    """Analyze request rates for both services."""
    end_ts = time.time()
    start_ts = end_ts - hours * 3600

    print(f"\n{'='*60}")
    print("REQUEST RATES")
    print(f"{'='*60}")

    # UserManager request rate
    um_rate_query = 'rate(user_manager_requests_total[5m])'
    um_rates = prom_query_range(um_rate_query, start_ts, end_ts, STEP_SECONDS)

    # DataCollector request rate
    dc_rate_query = 'rate(data_collector_requests_total[5m])'
    dc_rates = prom_query_range(dc_rate_query, start_ts, end_ts, STEP_SECONDS)

    if um_rates or dc_rates:
        plt.figure(figsize=(12, 6))

        if um_rates:
            times = [datetime.fromtimestamp(ts) for ts, _ in um_rates]
            values = [v for _, v in um_rates]
            plt.plot(times, values, label="UserManager", marker='o', markersize=3)

        if dc_rates:
            times = [datetime.fromtimestamp(ts) for ts, _ in dc_rates]
            values = [v for _, v in dc_rates]
            plt.plot(times, values, label="DataCollector", marker='s', markersize=3)

        plt.xlabel("Time")
        plt.ylabel("Requests per Second (5m rate)")
        plt.title(f"Request Rates - Last {hours} Hour(s)")
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        
        import os
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        output_file = f"{OUTPUT_DIR}/request_rates_{hours}h.png"
        plt.savefig(output_file, dpi=150)
        print(f"\nSaved chart: {output_file}")
        plt.close()
    else:
        print("No request rate data available")


# ----------------------- MAIN LOGIC -----------------------

def main():
    global PROMETHEUS_BASE_URL
    
    parser = argparse.ArgumentParser(description='DSBD Flight Tracker Metrics Reader')
    parser.add_argument('--hours', type=int, default=DEFAULT_RANGE_HOURS,
                        help=f'Time range in hours (default: {DEFAULT_RANGE_HOURS})')
    parser.add_argument('--prometheus-url', type=str, default=PROMETHEUS_BASE_URL,
                        help=f'Prometheus base URL (default: {PROMETHEUS_BASE_URL})')
    
    args = parser.parse_args()
    PROMETHEUS_BASE_URL = args.prometheus_url

    print(f"DSBD Flight Tracker - Prometheus Metrics Reader")
    print(f"Connecting to: {PROMETHEUS_BASE_URL}")
    print(f"Time range: Last {args.hours} hour(s)")

    # Analyze metrics
    analyze_user_manager_metrics(args.hours)
    analyze_data_collector_metrics(args.hours)
    analyze_request_rates(args.hours)

    print(f"\n{'='*60}")
    print("Analysis complete!")
    print(f"Charts saved to: {OUTPUT_DIR}/")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
