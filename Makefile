# Makefile, adopted from pydantic Makefile (https://github.com/pydantic/pydantic/blob/main/Makefile).

.DEFAULT_GOAL := all
sources = src/cupli tests
NUM_THREADS?=1

.PHONY: .uv  ## Check that uv is installed
.uv:
	@uv -V || echo 'Please install uv: https://docs.astral.sh/uv/getting-started/installation/'

.PHONY: .pre-commit  ## Check that pre-commit is installed
.pre-commit: .uv
	@uv run pre-commit -V || uv pip install pre-commit

.PHONY: install  ## Install the package, dependencies, and pre-commit for local development
install: .uv
	uv sync --frozen --all-groups --all-packages --all-extras
	uv pip install pre-commit
	uv run pre-commit install --install-hooks

.PHONY: upgrade-lock  ## Upgrade lock from scratch, updating all dependencies
upgrade-lock: .uv
	uv lock --upgrade

.PHONY: format  ## Auto-format python source files
format: .uv
	uv run ruff check --fix $(sources)
	uv run ruff format $(sources)

.PHONY: lint  ## Lint source files
lint: .uv
	uv run ruff check $(sources)
	uv run ruff format --check $(sources)

.PHONY: codespell  ## Use Codespell to do spellchecking
codespell: .pre-commit
	uv run pre-commit run codespell --all-files

.PHONY: typecheck  ## Perform type-checking
typecheck: .pre-commit
	uv run pre-commit run typecheck --all-files

.PHONY: schema  ## Regenerate space.schema.json from the Pydantic models
schema: .uv
	uv run python scripts/generate_schema.py

.PHONY: examples-validate  ## Validate every space.cupli.yaml under docs/examples/
examples-validate: .uv
	@for ex in docs/examples/*/space.cupli.yaml; do \
	  echo "validating $$ex"; \
	  uv run python -m cupli -f $$ex graph >/dev/null || exit 1; \
	done
	@echo "all examples valid."

.PHONY: test  ## Run all tests
test: .uv
	uv run coverage run -m pytest --durations=10

.PHONY: test-verbose  ## Run all tests, more verbose
test-verbose: .uv
	uv run coverage run -m pytest --durations=10 -vvvrP

.PHONY: smoke  ## Run docker-marked integration tests (skipped without a docker daemon)
smoke: .uv
	uv run pytest -o 'addopts=' -m docker --durations=10 -rs

.PHONY: testcov  ## Run tests and generate a coverage report
testcov: test
	@echo "building coverage html"
	@uv run coverage html
	@echo "building coverage lcov"
	@uv run coverage lcov

.PHONY: testcov-verbose  ## Run tests and generate a coverage report, more verbose
testcov-verbose: test-verbose
	@echo "building coverage html"
	@uv run coverage html
	@echo "building coverage lcov"
	@uv run coverage lcov

.PHONY: shell  ## Run IPython
shell: .uv
	uv run ipython

.PHONY: all  ## Run the standard set of checks performed in CI
all: schema lint typecheck codespell testcov examples-validate

.PHONY: clean  ## Clear local caches and build artifacts
clean:
	rm -rf `find . -name __pycache__`
	rm -f `find . -type f -name '*.py[co]'`
	rm -f `find . -type f -name '*~'`
	rm -f `find . -type f -name '.*~'`
	rm -rf .cache
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf htmlcov
	rm -rf *.egg-info
	rm -f .coverage
	rm -f .coverage.*
	rm -rf build
	rm -rf dist
	rm -rf site
	rm -rf docs/_build
	rm -rf docs/.changelog.md docs/.version.md docs/.tmp_schema_mappings.html
	rm -rf coverage.xml

.PHONY: help  ## Display this message
help:
	@grep -E \
		'^.PHONY: .*?## .*$$' $(MAKEFILE_LIST) | \
		sort | \
		awk 'BEGIN {FS = ".PHONY: |## "}; {printf "\033[36m%-19s\033[0m %s\n", $$2, $$3}'
