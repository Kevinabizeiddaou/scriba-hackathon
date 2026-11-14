# Desk backend overlay: standalone unit and route tests.
#
# The overlay runs inside Scriba's API process (see backend/README.md), so this image does
# not serve the API on its own. It runs the tests that need no Scriba checkout:
#
#   docker compose --profile test run --rm backend-tests
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend
COPY requirements-test.txt .
RUN pip install -r requirements-test.txt

COPY . .
CMD ["python", "-m", "pytest", "tests", "--ignore=tests/integration", "-q"]
