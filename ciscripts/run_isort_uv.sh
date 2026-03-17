#! /bin/bash
echo $PATH
set +e

PYFILESCHANGED=$(changedfiles --py)
if [[ -n "$PYFILESCHANGED" ]] ; then
    set -o pipefail
    source .venv/bin/activate
    isort -c --diff $PYFILESCHANGED | tee isort_all.txt
    res=$?
    set +o pipefail
else
    echo 'no python files changed'
    res=0
fi

set -e

exit $res
