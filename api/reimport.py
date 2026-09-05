"""Run the reference upsert from inside the container.

    docker compose exec api python -m api.reimport

For deployments that update their reference files by hand instead of running the
vars-sync sidecar: replace the files in the reference dir (a bind-mounted folder),
run this, read the stats. It is the same upsert the sidecar triggers — new variables
become concepts, changed ones (including the parquet-derived ones a special_vars
overlay regenerates) get a new version, identical ones are left alone, and nothing
is ever deleted.

The Notion documentation is pulled first, because nobody else pulls it in this mode:
with NOTION_API_KEY + NOTION_DATABASE_ID set, the export is fetched and written to
notion_docs.json before the upsert applies it (see api/notion_pull.py, which also
documents the column mapping and NOTION_FIELDS_FILE). Without them the pull is skipped
and the upsert runs on whatever is in the reference dir. A configured pull that *fails*
aborts before the upsert: applying yesterday's documentation while reporting success is
the outcome this ordering exists to prevent.

Deliberately upsert-only: the destructive force rebuild is not offered here, so
MODE=PRODUCTION deployments have no CLI back door around the API's refusal.
"""
import json
import sys

from .config import settings
from .importer import import_reference
from .notion_pull import pull_notion_docs


def main() -> int:
    try:
        documented = pull_notion_docs()
    except Exception as exc:  # every failure is fatal here, whatever its type
        print(f"notion docs pull failed ({exc!r}); not running the upsert", file=sys.stderr)
        return 2
    if documented is None:
        print("notion not configured (NOTION_API_KEY/NOTION_DATABASE_ID unset); docs pull skipped")
    else:
        print(
            f"notion docs pulled: {documented} documented concept(s) "
            f"-> {settings.reference_notion_docs_file}"
        )

    stats = import_reference()
    if stats is None:
        print("noop: key taxonomy or source not seeded", file=sys.stderr)
        return 1
    print(json.dumps(stats.as_dict(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
