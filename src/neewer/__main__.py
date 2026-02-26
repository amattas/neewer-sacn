"""Allow running as `python -m neewer`."""

import asyncio
import sys

from neewer.protocol import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ConnectionError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
