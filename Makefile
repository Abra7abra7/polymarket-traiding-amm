.PHONY: help test test-unit test-integration coverage install clean

help:
	@echo "Trading Bot — Make targets"
	@echo ""
	@echo "  make install        Install dependencies (pip install -r requirements.txt)"
	@echo "  make test           Run all tests (unit + integration)"
	@echo "  make test-unit      Run only unit tests (fast)"
	@echo "  make test-integration  Run integration / CLI tests"
	@echo "  make coverage       Generate coverage report (HTML in htmlcov/)"
	@echo "  make clean          Remove __pycache__, .pyc, coverage files"

install:
	pip install -r requirements.txt

test:
	pytest tests/ -v

test-unit:
	pytest tests/test_matrix.py tests/test_decision.py tests/test_client.py tests/test_config.py tests/test_logging.py tests/test_metrics.py tests/test_health.py -v

test-integration:
	pytest tests/test_integration.py tests/test_cli.py -v

coverage:
	pytest tests/ --cov=polymarket_bot --cov-report=html
	@echo "📊 Coverage report: file://$(PWD)/htmlcov/index.html"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .coverage htmlcov/ .pytest_cache 2>/dev/null || true
	@echo "✅ Cleaned"
