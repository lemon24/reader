.PHONY:

all: test

install-dev:
	pip install -q -e '.[cli,web-app,enclosure-tags,plugins]'
	pip install -q -r test-requirements.txt
	pip install -q pytest-xdist
	pip install -q pytest-cov

test: clean-pyc install-dev
	pytest -v --runslow

coverage: clean-pyc install-dev
	pytest --cov -n 4 -v --runslow
	coverage html

cov: coverage

clean-pyc:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -rf {} +

