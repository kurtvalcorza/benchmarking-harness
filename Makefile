# Convenience targets (see quickstart.md for the full walkthrough)

.PHONY: install test gates demo api worker frontend lint samples

install:
	pip install -e "backend[dev]"
	cd frontend && npm install

test:
	cd backend && pytest -q
	cd frontend && npm test

# The constitution gates that must stay green on every push (T019/T020/T067)
gates:
	cd backend && pytest -q \
		tests/contract/test_no_restricted_data.py \
		tests/contract/test_no_auto_approval.py \
		tests/contract/test_sandbox_no_egress.py

# Offline demo: inline evaluation, subprocess sandbox, stub models
demo:
	HARNESS_EVAL_MODE=inline HARNESS_SANDBOX_MODE=subprocess \
		uvicorn app.main:app --app-dir backend --port 8000 & \
	sleep 2 && python scripts/seed_demo.py && \
	echo "API on :8000 — press Ctrl+C to stop" && wait

api:
	uvicorn app.main:app --app-dir backend --reload --port 8000

worker:
	cd backend && python -m worker.main

frontend:
	cd frontend && npm run dev

lint:
	ruff check backend
	cd frontend && npm run lint

samples:
	python scripts/gen_samples.py
