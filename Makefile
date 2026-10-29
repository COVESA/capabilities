# Capability framework - standards and catalog tasks.
#
#   make bootstrap   create/refresh the venv (requirements + this package)
#   make vendor      verify pins, regenerate VSS/VDM artifacts, verify hashes
#   make check       run the capability rule checker over the catalog
#   make test        run the test suite
#   make paths       regenerate the VSS path constants
#   make graph       export the knowledge graph for docs
#   make standards   vendor + paths + check + test
PY ?= .venv/bin/python

.PHONY: bootstrap vendor paths graph check test standards

bootstrap:
	./bootstrap.sh

vendor:
	./scripts/vendor_standards.sh

check:
	PYTHONPATH=src $(PY) -m capability_framework.checker --strict

paths:
	$(PY) scripts/gen_vss_paths.py

graph:
	$(PY) scripts/export_graph.py
	$(PY) scripts/export_graph.py --check

test:
	PYTHONPATH=src $(PY) -m pytest tests -q

standards: vendor paths graph
	$(MAKE) check test
