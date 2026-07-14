"""Allow ``python -m mailslice`` as an alias for the console script."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
