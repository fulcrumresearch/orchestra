#!/usr/bin/env python3
# Forward Claude hook events to monitoring server
# Args: session_id source_path

import sys
import json
import urllib.request

session_id = sys.argv[1]
source_path = sys.argv[2]

try:
    # Read and parse hook event from stdin
    event = json.loads(sys.stdin.read())

    # Add source_path
    event['source_path'] = source_path

    # POST to monitor server
    urllib.request.urlopen(
        urllib.request.Request(
            f"http://host.docker.internal:8081/hook/{session_id}",
            data=json.dumps(event).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        ),
        timeout=5
    )
except Exception:
    pass
