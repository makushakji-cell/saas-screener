"""Write a self-contained static copy of the screener for GitHub Pages.

    python -m saasscreener.publish

The interactive app talks to a local Python server. That is fine on your own
machine and useless as a link someone else can open, so this writes the whole
screener out as plain files: the same HTML, CSS and JavaScript, plus a single
`data.json` holding everything the API would have returned.

The web app tries its API first and falls back to that file, so one codebase
serves both the live local version and the published one. The published copy
has frozen data and no refresh button -- it says the date it was built instead.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone

from . import config, server

DOCS = config.ROOT / "docs"


def main() -> int:
    if not config.DB_PATH.exists():
        print(f"No database at {config.DB_PATH}. Run: python -m saasscreener.build")
        return 1

    payload = server.screener_payload()
    payload["static"] = True
    payload["published_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    DOCS.mkdir(exist_ok=True)
    for name in ("index.html", "app.js", "style.css"):
        shutil.copy2(config.WEB / name, DOCS / name)

    (DOCS / "data.json").write_text(json.dumps(payload, default=str, separators=(",", ":")))
    # The live app offers a CSV from an endpoint; a published copy needs it as
    # a file, so write the same export out beside the data.
    (DOCS / "screener.csv").write_text(server.export_csv())
    # Tells GitHub Pages not to run the files through Jekyll, which would
    # otherwise ignore anything it considers a special filename.
    (DOCS / ".nojekyll").write_text("")

    size = (DOCS / "data.json").stat().st_size
    print(f"Wrote {DOCS}")
    print(f"  data.json  {size/1024:.0f} KB  ({len(payload['companies'])} companies)")
    print(f"  built from data as of {payload['companies'][0].get('quoted_at')}")
    print()
    print("Commit and push, then enable Pages:  Settings > Pages > main / docs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
