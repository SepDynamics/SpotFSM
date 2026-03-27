.PHONY: install build-manifold-engine probe-once probe-poll bridge-once bridge-poll list-spot-series replay-real test lint clean

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
PYTEST ?= $(PYTHON) -m pytest
PYTHONPATH ?= .
BUILD_DIR ?= build
BRIDGE_CONFIG ?= config/llm_routing.example.yaml
REPLAY_CONFIG ?= config/telemetry_policy.example.yaml

install:
	$(PIP) install --no-cache-dir -r requirements.txt

build-manifold-engine:
	cmake -S . -B $(BUILD_DIR)
	cmake --build $(BUILD_DIR) --target manifold_engine -j

probe-once:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m scripts.llm_probe.poller --config $(BRIDGE_CONFIG) --once

probe-poll:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m scripts.llm_probe.poller --config $(BRIDGE_CONFIG)

bridge-once:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m scripts.telemetry_bridge.cli --config $(BRIDGE_CONFIG) --once

bridge-poll:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m scripts.telemetry_bridge.cli --config $(BRIDGE_CONFIG)

list-spot-series:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m scripts.spotfsm.replay --config $(REPLAY_CONFIG) --list-top-series

replay-real:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m scripts.spotfsm.replay --config $(REPLAY_CONFIG)

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTEST)

lint:
	$(PYTHON) -m compileall scripts tests

clean:
	rm -rf $(BUILD_DIR) __pycache__ */__pycache__ */*/__pycache__ .pytest_cache .mypy_cache
