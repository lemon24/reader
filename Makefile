.PHONY:

all: clean test

test:
	python3 -m pytest

clean:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -rf {} +
	rm -rf reader.egg-info

