ifeq ($(OS),Windows_NT)
PYTHON ?= .venv/Scripts/python.exe
else
PYTHON ?= .venv/bin/python
endif
JOBS ?= 4

.PHONY: all validate verify rebuild test test-full train summarize
all:
	$(PYTHON) -m castguard all --jobs $(JOBS)
validate:
	$(PYTHON) -m castguard validate
verify:
	$(PYTHON) -m castguard verify
rebuild:
	$(PYTHON) -m castguard rebuild-check
test:
	$(PYTHON) -I -B run_review_tests.py --source-only
test-full:
	$(PYTHON) -I -B run_review_tests.py
train:
	$(PYTHON) -m castguard run --jobs $(JOBS)
summarize:
	$(PYTHON) -m castguard summarize
