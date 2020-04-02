.PHONY:

all: test

install-dev:
	pip install -q -e '.[cli,web-app,enclosure-tags,preview-feed-list,plugins,search,dev]'

test: clean-pyc install-dev
	pytest -v --runslow

coverage: clean-pyc install-dev
	pytest --cov -v --runslow
	coverage html
	coverage report --include '*/reader/core/*,*/reader/__init__.py' --fail-under 100 >/dev/null

cov: coverage

# mypy is not working on pypy as of January 2020
# https://github.com/python/typed_ast/issues/97#issuecomment-484335190
typing: clean-pyc install-dev
	test $$( python -c 'import sys; print(sys.implementation.name)' ) != pypy \
	&& mypy --strict src/reader/core \
	|| echo "mypy is not working on pypy, doing nothing"

test-all: install-dev
	tox

docs: clean-pyc install-dev
	 $(MAKE) -C docs html

clean-pyc:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -rf {} +
