.PHONY: clean clean-demo \
	guirc check setupcheck test testall test-coverage lint \
	changelint manualrelease release help

SHELL = /bin/bash

RCC5 = pyrcc5
RCC6 = /usr/lib64/qt6/libexec/rcc
UV = /usr/bin/env uv
UV_RUN = $(UV) run --all-extras --all-groups --all-packages

nicos/guisupport/gui_rc_qt5.py: resources/nicos-gui.qrc
	-$(RCC5) -o $@ $<

nicos/guisupport/gui_rc_qt6.py: resources/nicos-gui.qrc
	-$(RCC6) -g python $< | sed s,PySide6,PyQt6, > $@

guirc: nicos/guisupport/gui_rc_qt5.py nicos/guisupport/gui_rc_qt6.py

clean:
	rm -rf build
	find . -name '__pycache__' -exec rm -rf {} +
	rm -rf test/root/

clean-demo: clean
	-rm -rf data/cache/*
	-rm -rf data/logbook data/20*
	-rm -rf log/poller* log/cache log/daemon log/elog log/nicos log/watchdog log/simulation log/monitor*
	-rm -f data/current

check:
	$(UV_RUN) tools/check-setups $(CHECK_DIRS)

setupcheck:
	@$(UV_RUN) tools/check-setups -s $(shell find . -mindepth 3 -type d -name setups | grep -v /test/) $(shell find . -name guiconfig.py)

T =

test:
	@$(UV_RUN) pytest -v $(T) --durations=20 --ignore test/test_stresstest $(O)

testall:
	@$(UV_RUN) pytest -v $(T) --durations=20 $(O)

test-coverage:
	@COVERAGE_PROCESS_START=.coveragerc \
		$(UV_RUN) pytest -v $(T) --cov --cov-report=html --cov-report=term $(O)

lint:
	@-PYTHONPATH=.:${PYTHONPATH} $(UV_RUN) pylint --rcfile=./pylintrc nicos/ nicos_*/ nicostools/ tools/* bin/*

changelint:
	@PYFILESCHANGED=$$(git diff --name-only --diff-filter=dux HEAD^...HEAD | grep "\.py$$" | grep -v setups) ; \
	if [[ -n "$$PYFILESCHANGED" ]]; then \
		PYTHONPATH=.:${PYTHONPATH} $(UV_RUN) pylint --rcfile=./pylintrc $$PYFILESCHANGED; \
	else echo 'no python files changed'; fi

manualrelease: test release

release:
	cd doc; rm -rf build/html; ${MAKE} html
	$(UV) build

codespell:
	@codespell .

fixups:
	@ast-grep scan -c tools/fixups/config

help:
	@echo "Development targets:"
	@echo "  pod-demo        - start nicos-demo pod using podman or docker"
	@echo "  clean-demo      - clean up files created by nicos-demo"
	@echo "  setupcheck      - run setup checks"
	@echo "  test            - run test suite"
	@echo "  test-coverage   - run test suite with coverage reporting"
	@echo "  lint            - check source with pylint"
	@echo "  changelint      - check source with pylint (only files in last commit)"
	@echo "  fixups          - check source with ast-grep"
	@echo "  codespell       - check source with codespell"
	@echo "  manualrelease   - create tarball for official release (for manual usage)"
	@echo "  release         - create tarball for official release(jenkins usage)"
