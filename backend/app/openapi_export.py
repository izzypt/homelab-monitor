"""Write the OpenAPI spec to a file: the Angular client is generated from it.

Usage: python -m app.openapi_export ../frontend/openapi.json
"""

import json
import sys

from app.main import app


def main(path: str) -> None:
    with open(path, "w") as f:
        json.dump(app.openapi(), f, indent=2, sort_keys=True)
        f.write("\n")


if __name__ == "__main__":
    main(sys.argv[1])
