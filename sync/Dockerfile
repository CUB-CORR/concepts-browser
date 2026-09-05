# TEMPORARY sidecar (see sync.py). A poller (httpx) that also generates the code editor's
# completion surface — which is why polars and pandas are here: pyapi.py introspects the
# *installed* packages, since the version a snippet actually runs against is the only honest
# answer to "what members does pl.DataFrame have". They are optional: without them the
# generation logs a warning and emits the rest, degrading the editor rather than the sync.
FROM python:3.13-slim

WORKDIR /srv
RUN pip install --no-cache-dir "httpx>=0.28" "polars>=1.42" "pandas>=2.2"

COPY sync.py pyapi.py row_source.py notion_fields.json ./

CMD ["python", "sync.py"]
