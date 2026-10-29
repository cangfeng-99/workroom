"""Entry point for WorkRoom.exe; also runnable from the source checkout."""

import sys
from pathlib import Path

APP = (
    Path(sys._MEIPASS)
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[1] / "workroom"
)
sys.path.insert(0, str(APP))

if __name__ == "__main__":
    if "--mcp" in sys.argv[1:]:
        from desktop_mcp import main

        args = list(sys.argv[1:])
        args.remove("--mcp")
        raise SystemExit(main(args))
    from desktop_runtime import main

    raise SystemExit(main())
