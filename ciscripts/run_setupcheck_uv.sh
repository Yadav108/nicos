#! /bin/bash

source .venv/bin/activate

uv run -- tools/check-setups -o setupcheck.log -s $(find . -mindepth 3 -type d -name setups | grep -v '\/test/') $(find . -name guiconfig.py) || ((res++)) || /bin/true

# temporary: ignore CARESS related messages
sed -i -e '/CARESS/d' setupcheck.log

sc2gerrit

exit $((res))
