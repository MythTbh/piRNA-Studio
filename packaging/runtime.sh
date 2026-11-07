# Sourced after changing into the app directory.
if [ -x .runtime/env/bin/python ]; then
  runner="$PWD/.runtime/env/bin/python"
  export PATH="$PWD/.runtime/env/bin:$PATH"
elif [ -x .venv/bin/python ]; then
  runner="$PWD/.venv/bin/python"
  export PATH="$PWD/.venv/bin:$PATH"
  if [ -x .perl/bin/perl ]; then export PATH="$PWD/.perl/bin:$PATH"; fi
else
  runner=""
fi
export DUSTER_PL="$PWD/.tools/TBr2_duster.pl"
export SRNAMAPPER_PL="$PWD/.tools/sRNAmapper.pl"
export PROTRAC_PL="$PWD/.tools/proTRAC_2.4.2.pl"

export PYTHONUTF8=1
