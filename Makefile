.PHONY: all install-dev test coverage cov typing test-all docs clean-pyc serve-dev

all: test

install-dev:
	pip install -e '.[search,cli,app,plugins,enclosure-tags,preview-feed-list,dev,docs]'

test:
	pytest -v --runslow

coverage:
	pytest --cov -v --runslow
	coverage html
	coverage report \
		--include '*/reader/*' \
		--omit '*/reader/__main__.py,*/reader/_cli*,*/reader/_config*,*/reader/_app/*,*/reader/_plugins/*,tests/*' \
		--fail-under 100

cov: coverage

# mypy is not working on pypy as of January 2020
# https://github.com/python/typed_ast/issues/97#issuecomment-484335190
typing:
	test $$( python -c 'import sys; print(sys.implementation.name)' ) = pypy \
	&& echo "mypy is not working on pypy, doing nothing" \
	|| mypy --strict src

test-all:
	tox

docs:
	 $(MAKE) -C docs html

clean-pyc:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -rf {} +

serve-dev:
	FLASK_DEBUG=1 FLASK_TRAP_BAD_REQUEST_ERRORS=1 \
	FLASK_APP=src/reader/_app/wsgi.py \
	READER_DB=db.sqlite flask run -h 0.0.0.0 -p 8000
