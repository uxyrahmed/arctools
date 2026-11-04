"""Check that every Python toolbox under toolboxes/ is well formed.

Runs without arcpy: each .pyt file is parsed, not imported, so this works on
any Python 3 install (for example on CI).

Checks, for each toolboxes/**/*.pyt file:
- it compiles
- it defines a Toolbox class whose __init__ sets self.label, self.alias and
  self.tools, with alias made of letters and numbers only
- self.tools is a list of class names defined in the same file
- each of those tool classes defines getParameterInfo and execute

Usage: python scripts/check_toolboxes.py [path ...]
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_TOOL_METHODS = ("getParameterInfo", "execute")


def self_assignments(func):
    """Map attribute name -> value node for every `self.<name> = ...` in func."""
    assigned = {}
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                assigned[target.attr] = node.value
    return assigned


def methods(cls):
    return {
        node.name: node
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def check_file(path):
    errors = []
    source = path.read_text(encoding="utf-8")
    try:
        compile(source, str(path), "exec")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"line {exc.lineno}: does not compile: {exc.msg}"]

    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}

    toolbox = classes.get("Toolbox")
    if toolbox is None:
        return ["no top-level class named Toolbox"]

    init = methods(toolbox).get("__init__")
    if init is None:
        return ["Toolbox has no __init__"]

    assigned = self_assignments(init)
    for attr in ("label", "alias", "tools"):
        if attr not in assigned:
            errors.append(f"Toolbox.__init__ does not set self.{attr}")

    alias = assigned.get("alias")
    if isinstance(alias, ast.Constant) and isinstance(alias.value, str):
        if not alias.value.isascii() or not alias.value.isalnum():
            errors.append(
                f"Toolbox alias {alias.value!r} must be letters and numbers only"
            )

    tools = assigned.get("tools")
    if tools is None:
        return errors
    if not isinstance(tools, (ast.List, ast.Tuple)):
        return errors + ["Toolbox self.tools must be a list of tool classes"]
    if not tools.elts:
        errors.append("Toolbox self.tools is empty")

    for elt in tools.elts:
        if not isinstance(elt, ast.Name):
            errors.append(f"line {elt.lineno}: self.tools entries must be class names")
            continue
        cls = classes.get(elt.id)
        if cls is None:
            errors.append(f"tool {elt.id} is listed in self.tools but not defined")
            continue
        defined = methods(cls)
        for name in REQUIRED_TOOL_METHODS:
            if name not in defined:
                errors.append(f"tool {elt.id} has no {name} method")

    return errors


def main(argv):
    if argv:
        paths = [Path(arg) for arg in argv]
    else:
        paths = sorted((ROOT / "toolboxes").rglob("*.pyt"))

    if not paths:
        print("No .pyt files found under toolboxes/")
        return 1

    failed = 0
    for path in paths:
        try:
            shown = path.resolve().relative_to(ROOT)
        except ValueError:
            shown = path
        errors = check_file(path)
        if errors:
            failed += 1
            for error in errors:
                # GitHub Actions annotation, shown inline on the PR.
                print(f"::error file={shown}::{error}")
                print(f"FAIL {shown}: {error}")
        else:
            print(f"ok   {shown}")

    print(f"\n{len(paths) - failed} of {len(paths)} toolboxes passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
