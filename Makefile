.PHONY: install build-manifold-engine bridge-once bridge-poll test lint clean

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
PYTEST ?= $(PYTHON) -m pytest
PYTHONPATH ?= .
BUILD_DIR ?= build
BRIDGE_CONFIG ?= config/telemetry_bridge.example.yaml

install:
	$(PIP) install --no-cache-dir -r requirements.txt

build-manifold-engine:
	cmake -S . -B $(BUILD_DIR)
	cmake --build $(BUILD_DIR) --target manifold_engine -j

bridge-once:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m scripts.telemetry_bridge.cli --config $(BRIDGE_CONFIG) --once

bridge-poll:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m scripts.telemetry_bridge.cli --config $(BRIDGE_CONFIG)

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTEST)

lint:
	$(PYTHON) -m compileall scripts tests

clean:
	rm -rf $(BUILD_DIR) __pycache__ */__pycache__ */*/__pycache__ .pytest_cache .mypy_cache
