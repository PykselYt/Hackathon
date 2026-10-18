# Sourced by the other scripts (bash or zsh): activates the venv and points SUMO_HOME at the eclipse-sumo wheel.
if [ -n "${BASH_SOURCE[0]:-}" ]; then _env_src="${BASH_SOURCE[0]}"; else _env_src="$0"; fi
ROOT="$(cd "$(dirname "$_env_src")/.." && pwd)"
unset _env_src
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
export SUMO_HOME="${SUMO_HOME:-$(python -c 'import sumo; print(sumo.SUMO_HOME)')}"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
