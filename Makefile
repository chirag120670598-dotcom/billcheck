# Everything a release needs, in the order a release needs it.
.PHONY: install test samples site check clean

install:
	pip install -e ".[dev]"

# The samples are generated, so regenerating them is part of checking that the
# tests still describe reality rather than a stale set of files.
samples:
	python tools/make_samples.py

test:
	python -m pytest tests/ -q

# The landing page carries its own checker; it must agree with the Python one.
site:
	node tools/check_site.js

check: samples test site
	@python -m billcheck data/samples/*.pdf data/samples/*.txt --quiet \
		&& echo "all samples clean" || echo "samples reported findings (expected: 5)"

clean:
	rm -rf build dist *.egg-info .pytest_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
