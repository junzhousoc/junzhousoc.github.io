"""Record one synchronization health check per UTC month in repository history."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def record_health(path, outcome, now=None):
    now = now or datetime.now(timezone.utc)
    month = now.strftime('%Y-%m')
    if path.exists() and json.loads(path.read_text()).get('month') == month:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        'schema': 1,
        'month': month,
        'checked_at': now.isoformat(),
        'source_sync_outcome': outcome,
        'purpose': 'Monthly synchronization health record; maintains repository activity.'
    }, indent=2) + '\n')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--outcome', required=True, choices=['success', 'failure', 'cancelled', 'skipped'])
    parser.add_argument('--output', type=Path, default=Path('.sync/health.json'))
    args = parser.parse_args()
    print('Monthly health record updated.' if record_health(args.output, args.outcome) else 'This month is already recorded.')
