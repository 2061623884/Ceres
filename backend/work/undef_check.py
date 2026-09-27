"""Ad-hoc undefined-name checker (static only; no imports of project code).

Used during the request-level graph refactor because no linter is installed in
this environment. It is conservative: findings are candidates to review, not
proof. Run with ``python work/undef_check.py app scripts``.
"""

import ast
import builtins
import pathlib
import sys

BUILTINS = set(dir(builtins)) | {
    "__name__",
    "__file__",
    "__doc__",
    "__package__",
    "__all__",
    "__builtins__",
    "WindowsError",
}

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def bind_target(node, out):
    if isinstance(node, ast.Name):
        out.add(node.id)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for element in node.elts:
            bind_target(element, out)
    elif isinstance(node, ast.Starred):
        bind_target(node.value, out)


def walk_no_scope(node):
    """Yield descendants without entering nested scopes' bodies."""
    stack = list(ast.iter_child_nodes(node))
    while stack:
        current = stack.pop()
        yield current
        if isinstance(current, _SCOPES):
            continue
        stack.extend(ast.iter_child_nodes(current))


def local_bindings(body):
    names = set()
    for stmt in body:
        for node in [stmt, *walk_no_scope(stmt)]:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name != "*":
                        names.add(alias.asname or alias.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    bind_target(target, names)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr)):
                bind_target(node.target, names)
            elif isinstance(node, ast.For):
                bind_target(node.target, names)
            elif isinstance(node, ast.AsyncFor):
                bind_target(node.target, names)
            elif isinstance(node, ast.comprehension):
                bind_target(node.target, names)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.optional_vars is not None:
                        bind_target(item.optional_vars, names)
            elif isinstance(node, ast.ExceptHandler):
                if node.name:
                    names.add(node.name)
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(stmt.name)
    return names


def arg_names(args):
    names = set()
    for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
        names.add(arg.arg)
    if args.vararg:
        names.add(args.vararg.arg)
    if args.kwarg:
        names.add(args.kwarg.arg)
    return names


def check_names_in(node, known, problems):
    extra = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.comprehension):
            bind_target(sub.target, extra)
    known = set(known) | extra
    for sub in [node, *walk_no_scope(node)]:
        if (
            isinstance(sub, ast.Name)
            and isinstance(sub.ctx, ast.Load)
            and sub.id not in known
        ):
            problems.add((sub.lineno, sub.id))


def check_body(body, known, problems):
    known = set(known) | local_bindings(body) | BUILTINS
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            check_function(stmt, known, problems)
        elif isinstance(stmt, ast.ClassDef):
            check_class(stmt, known, problems)
        else:
            check_names_in(stmt, known, problems)
            for sub in walk_no_scope(stmt):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    check_function(sub, known, problems)
                elif isinstance(sub, ast.ClassDef):
                    check_class(sub, known, problems)
                elif isinstance(sub, ast.Lambda):
                    check_lambda(sub, known, problems)


def check_function(node, outer_known, problems):
    known = set(outer_known) | arg_names(node.args)
    check_body(node.body, known, problems)


def check_lambda(node, outer_known, problems):
    known = set(outer_known) | arg_names(node.args)
    check_names_in(node.body, known, problems)
    for sub in walk_no_scope(node.body):
        if isinstance(sub, ast.Lambda):
            check_lambda(sub, known, problems)


def check_class(node, outer_known, problems):
    known = set(outer_known) | {node.name}
    check_body(node.body, known, problems)


def check_file(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    problems = set()
    check_body(tree.body, set(), problems)
    return sorted(problems)


def main(roots):
    files = []
    for root in roots:
        path = pathlib.Path(root)
        files += [path] if path.is_file() else sorted(path.rglob("*.py"))
    total = 0
    for path in files:
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        try:
            problems = check_file(path)
        except SyntaxError as exc:
            print(f"{path}: SYNTAX {exc}")
            total += 1
            continue
        for line, name in problems:
            print(f"{path}:{line}: possibly undefined name {name!r}")
            total += 1
    print(f"checked {len(files)} files, {total} findings")


if __name__ == "__main__":
    main(sys.argv[1:])
