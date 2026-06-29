#! /bin/bash
set -x
set +e

PYFILESCHANGED=$(changedfiles --py)

source .venv/bin/activate
if [[ -n "$PYFILESCHANGED" ]] ; then
    set -o pipefail
    uv run -- pylint --rcfile=./pylintrc $PYFILESCHANGED | tee pylint_all.txt
    res=$?
    set +o pipefail
else
    echo 'no python files changed'
    res=0
fi

set -e

pylint2gerrit

exit $res
