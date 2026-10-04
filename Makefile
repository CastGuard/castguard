PYTHON ?= python
JOBS ?=

.PHONY: all env prepare train analyze report test quick
all:
	$(PYTHON) -m castguard all $(if $(JOBS),--jobs $(JOBS),)
env prepare train analyze report:
	$(PYTHON) -m castguard $@ $(if $(JOBS),--jobs $(JOBS),)
quick:
	$(PYTHON) -m castguard all --quick
test:
	$(PYTHON) -m pytest -q tests
