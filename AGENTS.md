# NICOS Agent Guide

## Project Overview

NICOS is the Networked Instrument Control System used at MLZ (Germany's
neutron science facility). This is a monorepo with:
- `nicos/` — core package
- `nicos_*/` — facility-specific packages (`nicos_mlz`, `nicos_ess`, `nicos_demo`, etc.)
- `nicostools/` — utilities

## Dev Commands

```bash
make test                       # run tests (excludes test_stresstest)
make testall                    # run all tests including stress test suite
make test-coverage              # with coverage reporting
make lint                       # pylint on nicos/ nicos_*/ nicostools/ tools/ bin/
make setupcheck                 # validate setup files and guiconfig
make check                      # check setups (CHECK_DIRS env var)
```

Single test: `python -m pytest -v path/to/test.py::test_name`

## Dev Process

- Primary review is Gerrit at forge.frm2.tum.de, mirrored read-only on GitHub
- Gerrit prefers commits over branches as units-of-review - before pushing,
  squash changes into logical units with good commit messages

## Architecture

- **Overview (important)**: read @doc/source/overview.rst
- **Misc dev docs**: read files linked by @doc/source/developer.rst
- **Entry points**: All in `bin/` — `nicos-gui`, `nicos-client`, `nicos-daemon`, `nicos-cache`, `nicos-poller`, `nicos-elog`, `nicos-watchdog`, `nicos-simulate`
- **Configuration**: `nicos.conf` (TOML) in install prefix; `setup_package` and `instrument` must be set
- **Setups**: Python files defining devices; loaded at session startup
- **GUI**: PyQt5/PyQt6 with QtWebEngine; generated `gui_rc_qt5.py`/`gui_rc_qt6.py` from `.qrc`

## Code Style

- PEP-8 based, 132-char line limit, enforced via pylint + isort
- isort order: STDLIB, THIRDPARTY, CORE (nicos), FIRSTPARTY, FACILITY (nicos_*),
  TESTMOD, LOCALFOLDER
- Version support: Python 3.9–3.13; NumPy <2.0 (no NumPy 2.x compatibility yet)
- Docstrings are only required for classes and non-overridden public methods;
  document private things only if they are not obvious from a glance
- `additional-builtins` for NICOS DSL in setups: `device`, `setupname`,
  `configdata`, `Row`, `Column`, `Block`, `Field`, `panel`, `window`, etc.

## Testing Notes

- Fixtures in `test/fixtures/` (setup_test_suite, session, log, dataroot, guiclient)
- Tests create `test/root/` directory for daemon working directory
- GUI tests need a display (uses pytest-xvfb by default in dev environments)
- `make clean` removes `test/root/`; don't rely on persisted state across test runs
- Some tests require external services (Kafka, InfluxDB) — see test_all suite in Jenkinsfile
- Test modules that create devices declare a setup at module level:
  `session_setup = 'name'` loads `test/setups/name.py`
- `log.assert_warns(regex=None, count=None)`, `log.assert_errors(...)`,
  `log.allow_errors()`
- Test errors that are logged raise by default — wrap in `log.allow_errors()` to avoid
- Tests are slow: per-test timeout is 300s (pytest.ini), session timeout 1800s
