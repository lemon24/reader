.PHONY:

all: test

test: clean-pyc
	python3 -m pytest -v --runslow

coverage: clean-pyc
	coverage run -p -m pytest -v --runslow
	coverage combine
	coverage report
	coverage html

cov: coverage

clean-pyc:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -rf {} +

