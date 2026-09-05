"""Static snapshot data exported from AliCPT production ES/MongoDB.

v4.24: Clarified that this is a point-in-time export, NOT live data.
The _data_export_date field indicates when the snapshot was taken.
All functions return [] if the JSON files are not found on disk.
"""
import json, os

_data_dir = os.path.dirname(__file__)

# Data export timestamps — populated on first load
_data_export_dates: dict[str, str] = {}

def get_data_export_dates() -> dict[str, str]:
    """Return the export dates of all loaded snapshot files.
    Returns empty dict if no files have been loaded yet.
    """
    return dict(_data_export_dates)


def _load(name):
    path = os.path.join(_data_dir, '..', '..', 'real-data', f'{name}.json')
    # Support running from both host and Docker container
    if not os.path.exists(path):
        path = os.path.join(_data_dir, f'{name}.json')
    if not os.path.exists(path):
        path = os.path.join('/app/real-data', f'{name}.json')
    if os.path.exists(path):
        # Record file modification time as data export date
        mtime = os.path.getmtime(path)
        from datetime import datetime, timezone
        _data_export_dates[name] = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(path, 'r') as f:
            return json.load(f)
    return []

def get_observations():
    return _load('observations_clean')

def get_errors():
    return _load('errors_clean')

def get_details():
    return _load('details_clean')

def get_comments():
    return _load('comments')
