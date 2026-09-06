#!/usr/bin/env python3
"""Review database migration files for the operations that lock tables,
lose data, or cannot be undone, as a finding-list
(kit/shapes/finding-list.schema.json).

Usage:
    review_migrations.py <migrations-dir> [--exclude dir,dir]

Effect Ladder rung 1 (SDS-S-060): files are read with `ast` (Python)
and a line scanner (SQL); nothing is executed and no database is
contacted. Three dialects are recognised by shape, not by framework
import:

    Alembic   Python files calling op.<name>(...) in upgrade()/downgrade()
    Django    Python files with a Migration class whose `operations`
              list holds migrations.<Name>(...)
    SQL       .sql files, statement by statement

Rules emitted (the expand/migrate/contract order of
migration-plan-writer is the reference: a destructive step belongs in
the contract phase, after usage has moved):

    migration/destructive        DROP TABLE, DROP COLUMN, op.drop_table,
                                 op.drop_column, DeleteModel,
                                 RemoveField -> error (data is gone;
                                 must follow a verified migrate phase)
    migration/not-null-no-default ADD COLUMN ... NOT NULL without DEFAULT,
                                 op.add_column(nullable=False) without
                                 server_default, AddField(null=False)
                                 without default -> error (fails on any
                                 existing row)
    migration/type-change        ALTER COLUMN ... TYPE, op.alter_column
                                 with type_=, AlterField -> warning
                                 (rewrites the table under a lock;
                                 add a new column instead)
    migration/index-not-concurrent CREATE INDEX without CONCURRENTLY,
                                 op.create_index without
                                 postgresql_concurrently=True, AddIndex
                                 -> warning (blocks writes for the
                                 build)
    migration/irreversible       downgrade() whose body is only pass,
                                 RunPython without reverse_code, a
                                 .sql file with no paired *_down.sql /
                                 -- down section -> warning
    migration/ddl-with-dml       a data change (op.execute with
                                 UPDATE/INSERT, RunPython, UPDATE/
                                 INSERT statements) in the same file
                                 as a schema change -> info (one
                                 transaction, two failure modes;
                                 split them)

Whether a finding is acceptable here — a drop of a column nothing has
read for a month, a NOT NULL on an empty table — is the skill's
Analyze stage (SDS-S-061).

Prints one finding-list; a directory of safe migrations yields an
empty `results` array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr
for a path that is not a directory (migrations-dir-invalid) or a
Python migration that does not parse (migration-unparseable).
"""
import ast
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".skills-state"}
SQL_RULES = [
    ("migration/destructive", "error", re.compile(r"\bDROP\s+(TABLE|COLUMN)\b", re.I), "drops data"),
    ("migration/not-null-no-default", "error", re.compile(r"\bADD\s+(COLUMN\s+)?\w+\s+[^,;]*\bNOT\s+NULL\b(?![^;]*\bDEFAULT\b)", re.I), "NOT NULL without DEFAULT fails on existing rows"),
    ("migration/type-change", "warning", re.compile(r"\bALTER\s+COLUMN\s+\w+\s+(SET\s+DATA\s+)?TYPE\b", re.I), "rewrites the table under a lock"),
    ("migration/index-not-concurrent", "warning", re.compile(r"\bCREATE\s+(UNIQUE\s+)?INDEX\b(?!\s+CONCURRENTLY)", re.I), "blocks writes while the index builds"),
]
SQL_DML = re.compile(r"^\s*(UPDATE|INSERT|DELETE)\b", re.I | re.M)
SQL_DDL = re.compile(r"^\s*(CREATE|ALTER|DROP)\b", re.I | re.M)


def finding(rule, level, text, uri, line, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}, "region": {"startLine": line}}}],
            "properties": props}


def kw(call, name):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def const(node):
    return node.value if isinstance(node, ast.Constant) else None


def call_name(call):
    f = call.func
    if isinstance(f, ast.Attribute):
        base = f.value.id if isinstance(f.value, ast.Name) else None
        return base, f.attr
    if isinstance(f, ast.Name):
        return None, f.id
    return None, None


def review_python(tree, uri, out):
    ddl, dml = False, False
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    if "downgrade" in funcs and all(isinstance(s, ast.Pass) or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)) for s in funcs["downgrade"].body):
        out.append(finding("migration/irreversible", "warning", "downgrade() is empty; this migration cannot be rolled back", uri, funcs["downgrade"].lineno, {"dialect": "alembic"}))
    # Alembic ops inside downgrade() are the rollback, not the change: scope them out
    downgrade_calls = {id(n) for n in ast.walk(funcs["downgrade"]) if isinstance(n, ast.Call)} if "downgrade" in funcs else set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        base, name = call_name(node)
        ln = node.lineno
        # Alembic
        if base == "op" and id(node) not in downgrade_calls:
            if name in ("drop_table", "drop_column"):
                ddl = True
                out.append(finding("migration/destructive", "error", f"op.{name} drops data; belongs in the contract phase after usage has moved", uri, ln, {"dialect": "alembic", "op": name}))
            elif name == "add_column":
                ddl = True
                col = node.args[1] if len(node.args) > 1 else None
                if isinstance(col, ast.Call) and const(kw(col, "nullable")) is False and kw(col, "server_default") is None:
                    out.append(finding("migration/not-null-no-default", "error", "op.add_column with nullable=False and no server_default fails on existing rows", uri, ln, {"dialect": "alembic"}))
            elif name == "alter_column":
                ddl = True
                if kw(node, "type_") is not None:
                    out.append(finding("migration/type-change", "warning", "op.alter_column(type_=…) rewrites the table under a lock; add a new column and migrate instead", uri, ln, {"dialect": "alembic"}))
            elif name == "create_index":
                ddl = True
                if const(kw(node, "postgresql_concurrently")) is not True:
                    out.append(finding("migration/index-not-concurrent", "warning", "op.create_index without postgresql_concurrently=True blocks writes while the index builds", uri, ln, {"dialect": "alembic"}))
            elif name in ("create_table", "add_constraint", "drop_constraint", "rename_table", "create_foreign_key"):
                ddl = True
            elif name == "execute":
                sql = const(node.args[0]) if node.args else None
                if isinstance(sql, str) and SQL_DML.search(sql):
                    dml = True
                elif isinstance(sql, str) and SQL_DDL.search(sql):
                    ddl = True
        # Django
        if base == "migrations":
            if name in ("DeleteModel", "RemoveField"):
                ddl = True
                out.append(finding("migration/destructive", "error", f"migrations.{name} drops data; belongs in the contract phase after usage has moved", uri, ln, {"dialect": "django", "op": name}))
            elif name == "AddField":
                ddl = True
                field = kw(node, "field")
                if isinstance(field, ast.Call) and const(kw(field, "null")) is not True and kw(field, "default") is None:
                    out.append(finding("migration/not-null-no-default", "error", "migrations.AddField with a non-null field and no default fails on existing rows", uri, ln, {"dialect": "django"}))
            elif name == "AlterField":
                ddl = True
                out.append(finding("migration/type-change", "warning", "migrations.AlterField may rewrite the table under a lock; check the field type change", uri, ln, {"dialect": "django"}))
            elif name == "AddIndex":
                ddl = True
                out.append(finding("migration/index-not-concurrent", "warning", "migrations.AddIndex builds the index under a lock; use AddIndexConcurrently (django.contrib.postgres) with atomic = False", uri, ln, {"dialect": "django"}))
            elif name == "RunPython":
                dml = True
                if kw(node, "reverse_code") is None and len(node.args) < 2:
                    out.append(finding("migration/irreversible", "warning", "migrations.RunPython without reverse_code cannot be rolled back", uri, ln, {"dialect": "django"}))
            elif name in ("CreateModel", "RenameField", "RenameModel", "AlterUniqueTogether", "AddConstraint"):
                ddl = True
    if ddl and dml:
        out.append(finding("migration/ddl-with-dml", "info", "schema change and data change in one migration; one transaction, two failure modes — split them", uri, 1, {}))


def review_sql(text, uri, out, has_down):
    lines = text.splitlines()
    in_down = False
    for i, line in enumerate(lines, start=1):
        if re.match(r"^\s*--\s*(down|rollback)\b", line, re.I):
            in_down = True
        if in_down:
            continue
        for rule, level, rx, why in SQL_RULES:
            if rx.search(line):
                out.append(finding(rule, level, f"{line.strip()[:70]} — {why}", uri, i, {"dialect": "sql"}))
    up = text.split("-- down")[0] if "-- down" in text.lower() else text
    if not has_down and not re.search(r"^\s*--\s*(down|rollback)\b", text, re.I | re.M):
        out.append(finding("migration/irreversible", "warning", "no paired *_down.sql and no '-- down' section; this migration cannot be rolled back", uri, 1, {"dialect": "sql"}))
    if SQL_DDL.search(up) and SQL_DML.search(up):
        out.append(finding("migration/ddl-with-dml", "info", "schema change and data change in one file; split them", uri, 1, {"dialect": "sql"}))


def main():
    args = sys.argv[1:]
    exclude = set()
    if "--exclude" in args:
        i = args.index("--exclude")
        if i + 1 >= len(args):
            sys.exit("ERROR: --exclude requires a value")
        exclude = {x.strip() for x in args[i + 1].split(",") if x.strip()}
        del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: review_migrations.py <migrations-dir> [--exclude dir,dir]")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (migrations-dir-invalid): {root}")
    out = []
    files = [p for p in sorted(root.rglob("*")) if p.is_file() and p.suffix in (".py", ".sql") and not any(part in SKIP_DIRS or part in exclude for part in p.relative_to(root).parts)]
    sql_names = {p.name for p in files if p.suffix == ".sql"}
    for p in files:
        uri = p.relative_to(root).as_posix()
        text = p.read_text(encoding="utf-8")
        if p.suffix == ".py":
            if p.name == "__init__.py":
                continue
            try:
                tree = ast.parse(text, filename=str(p))
            except SyntaxError as e:
                sys.exit(f"ERROR: {uri} does not parse (migration-unparseable): {e}")
            review_python(tree, uri, out)
        else:
            if p.name.endswith("_down.sql") or p.name.endswith(".down.sql"):
                continue
            candidates = {p.name[:-4] + "_down.sql", p.name[:-4] + ".down.sql"}
            if p.name.endswith(".up.sql"):
                candidates.add(p.name[:-7] + ".down.sql")
            has_down = bool(candidates & sql_names)  # never the file itself
            review_sql(text, uri, out, has_down)
    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda r: (order[r["level"]], r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], r["locations"][0]["physicalLocation"]["region"]["startLine"], r["ruleId"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "schema-migration-review", "version": "0.1.0"},
                                         "properties": {"files": len(files), "blocking": sum(1 for r in out if r["level"] == "error")}},
                                "results": out}]}, indent=2))


if __name__ == "__main__":
    main()
