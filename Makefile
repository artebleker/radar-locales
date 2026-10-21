# Atajos para macOS y Linux. En Windows, usar los comandos equivalentes del README (sección «Windows»).
PY ?= python3

.PHONY: instalar bootstrap run smoke test serve report

instalar:
	$(PY) -m venv .venv
	.venv/bin/pip install -r requirements.txt
	.venv/bin/pip install --no-deps -e .

bootstrap:
	.venv/bin/radar bootstrap

run:
	.venv/bin/radar run

smoke:
	.venv/bin/radar run --limite 20 --dry-run

test:
	.venv/bin/pytest -q

serve:
	.venv/bin/radar serve

report:
	.venv/bin/radar report
