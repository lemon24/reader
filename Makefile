.PHONY:

all: test

install-dev:
	pip install -q -e '.[web-app,requests,enclosure-tags]'
	pip install -q -r test-requirements.txt
	pip install -q pytest-xdist

test: clean-pyc install-dev
	python3 -m pytest -v --runslow

coverage: clean-pyc install-dev
	coverage run -p -m pytest -n 4 -v --runslow
	coverage combine
	coverage report
	coverage html

cov: coverage

clean-pyc:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -rf {} +

