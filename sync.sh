#!/bin/bash
# Daily Skool sales sync — pulls latest members and regenerates dashboard
cd /Users/lukebyrne/Documents/skool-sales
/usr/bin/python3 tracker.py sync >> data/sync.log 2>&1
/usr/bin/python3 tracker.py dashboard --no-open >> data/sync.log 2>&1
echo "--- $(date) ---" >> data/sync.log
