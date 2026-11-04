"""Write docs/PARAMETERS.md from the parameter registry of the default build."""

from simchi.paths import ROOT
from simchi.pipeline import build
from simchi.registry import as_markdown, registry

if __name__ == "__main__":
    md = as_markdown(registry(build(2000, 1)))
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "PARAMETERS.md").write_text(md)
    print("docs/PARAMETERS.md:", md.count("\n| `"), "parameters")
