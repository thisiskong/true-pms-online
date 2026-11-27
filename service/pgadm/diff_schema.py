import argparse
import os
import re


def list_sql_files(root_dir, subfolder):
    dir_path = os.path.join(root_dir, subfolder)
    if not os.path.isdir(dir_path):
        return {}
    result = {}
    for fname in os.listdir(dir_path):
        if fname.endswith(".sql"):
            result[fname[:-4]] = os.path.join(dir_path, fname)
    return result


def normalize_body(text):
    text = text.rstrip()
    while text.endswith(";"):
        text = text[:-1].rstrip()
    return text


def parse_index_stmts(index_stmts):
    indexes = []
    for stmt in index_stmts:
        stmt = stmt.strip()
        if not stmt:
            continue
        match = re.match(r"CREATE (?:UNIQUE )?INDEX (\S+) ON", stmt)
        idx_name = match.group(1) if match else stmt
        indexes.append((idx_name, stmt))
    return indexes


def parse_table_file(path):
    with open(path, encoding="utf-8") as f:
        content = f.read()

    chunks = content.rstrip("\n").split("\n\n")
    table_stmt = chunks[0]
    lines = table_stmt.split("\n")

    last_line = lines[-1]
    partition_clause = None
    if last_line.startswith(") PARTITION BY "):
        partition_clause = last_line[len(") PARTITION BY "):].rstrip(";")

    columns = []
    constraints = []
    for line in lines[1:-1]:
        stripped = line.strip()
        if stripped.endswith(","):
            stripped = stripped[:-1]

        if stripped.startswith("CONSTRAINT "):
            name, con_def = stripped[len("CONSTRAINT "):].split(" ", 1)
            constraints.append((name, con_def))
            continue

        s = stripped
        notnull = False
        if s.endswith(" NOT NULL"):
            notnull = True
            s = s[: -len(" NOT NULL")]

        default = None
        marker = " DEFAULT "
        if marker in s:
            i = s.index(marker)
            default = s[i + len(marker):]
            s = s[:i]

        name, dtype = s.split(" ", 1)
        columns.append((name, dtype, notnull, default))

    return {
        "columns": columns,
        "constraints": constraints,
        "partition_clause": partition_clause,
        "indexes": parse_index_stmts(chunks[1:]),
    }


def parse_view_file(path):
    with open(path, encoding="utf-8") as f:
        content = f.read()
    idx = content.index(" AS\n")
    body = normalize_body(content[idx + len(" AS\n"):])
    return {"body": body, "raw_ddl": content.rstrip("\n")}


def parse_matview_file(path):
    with open(path, encoding="utf-8") as f:
        content = f.read()
    chunks = content.rstrip("\n").split("\n\n")
    main_stmt = chunks[0]
    idx = main_stmt.index(" AS\n")
    body = normalize_body(main_stmt[idx + len(" AS\n"):])
    return {"body": body, "raw_ddl": main_stmt, "indexes": parse_index_stmts(chunks[1:])}


def parse_sequence_file(path):
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    def after(prefix, line):
        return line.strip()[len(prefix):]

    return {
        "data_type": after("AS ", lines[1]),
        "start": after("START WITH ", lines[2]),
        "increment": after("INCREMENT BY ", lines[3]),
        "minvalue": after("MINVALUE ", lines[4]),
        "maxvalue": after("MAXVALUE ", lines[5]),
        "cache": after("CACHE ", lines[6]),
        "cycle": lines[7].strip().startswith("CYCLE"),
    }


def load_snapshot(root_dir):
    return {
        "tables": {k: parse_table_file(p) for k, p in list_sql_files(root_dir, "tables").items()},
        "views": {k: parse_view_file(p) for k, p in list_sql_files(root_dir, "views").items()},
        "mviews": {k: parse_matview_file(p) for k, p in list_sql_files(root_dir, "mviews").items()},
        "sequences": {k: parse_sequence_file(p) for k, p in list_sql_files(root_dir, "sequences").items()},
    }


def build_table_ddl_from_parsed(key, tabledef):
    col_defs = []
    for name, dtype, notnull, default in tabledef["columns"]:
        col_def = f"    {name} {dtype}"
        if default is not None:
            col_def += f" DEFAULT {default}"
        if notnull:
            col_def += " NOT NULL"
        col_defs.append(col_def)

    con_defs = [f"    CONSTRAINT {name} {con_def}" for name, con_def in tabledef["constraints"]]
    body = ",\n".join(col_defs + con_defs)

    lines = [f"CREATE TABLE {key} (", body]
    if tabledef["partition_clause"]:
        lines.append(f") PARTITION BY {tabledef['partition_clause']};")
    else:
        lines.append(");")
    return "\n".join(lines)


def build_sequence_ddl_from_parsed(key, seqdef, keyword="CREATE SEQUENCE"):
    lines = [
        f"{keyword} {key}",
        f"    AS {seqdef['data_type']}",
        f"    START WITH {seqdef['start']}",
        f"    INCREMENT BY {seqdef['increment']}",
        f"    MINVALUE {seqdef['minvalue']}",
        f"    MAXVALUE {seqdef['maxvalue']}",
        f"    CACHE {seqdef['cache']}",
    ]
    lines.append("    CYCLE;" if seqdef["cycle"] else "    NO CYCLE;")
    return "\n".join(lines)


def diff_table_columns(key, s, t):
    stmts = []
    s_cols = {c[0]: c for c in s["columns"]}
    t_cols = {c[0]: c for c in t["columns"]}

    for name in sorted(set(s_cols) - set(t_cols)):
        _, dtype, notnull, default = s_cols[name]
        col_def = f"{name} {dtype}"
        if default is not None:
            col_def += f" DEFAULT {default}"
        if notnull:
            col_def += " NOT NULL"
        stmts.append(f"ALTER TABLE {key} ADD COLUMN {col_def};")

    for name in sorted(set(t_cols) - set(s_cols)):
        stmts.append(f"ALTER TABLE {key} DROP COLUMN {name};")

    for name in sorted(set(s_cols) & set(t_cols)):
        _, s_dtype, s_notnull, s_default = s_cols[name]
        _, t_dtype, t_notnull, t_default = t_cols[name]
        if s_dtype != t_dtype:
            stmts.append(f"ALTER TABLE {key} ALTER COLUMN {name} TYPE {s_dtype};")
        if s_notnull != t_notnull:
            action = "SET" if s_notnull else "DROP"
            stmts.append(f"ALTER TABLE {key} ALTER COLUMN {name} {action} NOT NULL;")
        if s_default != t_default:
            if s_default is not None:
                stmts.append(f"ALTER TABLE {key} ALTER COLUMN {name} SET DEFAULT {s_default};")
            else:
                stmts.append(f"ALTER TABLE {key} ALTER COLUMN {name} DROP DEFAULT;")

    return stmts


def diff_table_constraints(key, s, t):
    stmts = []
    s_cons = {name: con_def for name, con_def in s["constraints"]}
    t_cons = {name: con_def for name, con_def in t["constraints"]}
    changed = [n for n in sorted(set(s_cons) & set(t_cons)) if s_cons[n] != t_cons[n]]

    for name in sorted(set(t_cons) - set(s_cons)) + changed:
        stmts.append(f"ALTER TABLE {key} DROP CONSTRAINT {name};")
    for name in sorted(set(s_cons) - set(t_cons)) + changed:
        stmts.append(f"ALTER TABLE {key} ADD CONSTRAINT {name} {s_cons[name]};")

    return stmts


def diff_table_indexes(key, s, t):
    stmts = []
    s_idx = dict(s["indexes"])
    t_idx = dict(t["indexes"])

    for name in sorted(set(t_idx) - set(s_idx)):
        stmts.append(f"DROP INDEX IF EXISTS {name};")
    for name in sorted(set(s_idx) - set(t_idx)):
        stmts.append(s_idx[name])
    for name in sorted(set(s_idx) & set(t_idx)):
        if s_idx[name] != t_idx[name]:
            stmts.append(f"DROP INDEX IF EXISTS {name};")
            stmts.append(s_idx[name])

    return stmts


def diff_tables(source, target):
    creates, modifies, drops = [], [], []

    for key in sorted(set(source) - set(target)):
        t = source[key]
        parts = [build_table_ddl_from_parsed(key, t)] + [stmt for _, stmt in t["indexes"]]
        creates.append(f"-- table: {key} (create)\n" + "\n\n".join(parts))

    for key in sorted(set(target) - set(source)):
        drops.append(f"-- table: {key} (drop)\nDROP TABLE IF EXISTS {key};")

    for key in sorted(set(source) & set(target)):
        s, t = source[key], target[key]
        stmts = (
            diff_table_columns(key, s, t)
            + diff_table_constraints(key, s, t)
            + diff_table_indexes(key, s, t)
        )
        if s["partition_clause"] != t["partition_clause"]:
            stmts.append(
                f"-- WARNING: partition clause differs for {key} "
                f"(source: {s['partition_clause']}, target: {t['partition_clause']}) "
                f"-- requires manual table recreation"
            )
        if stmts:
            modifies.append(f"-- table: {key}\n" + "\n".join(stmts))

    return creates, modifies, drops


def diff_views(source, target):
    creates, modifies, drops = [], [], []

    for key in sorted(set(source) - set(target)):
        creates.append(f"-- view: {key} (create)\n{source[key]['raw_ddl']}")

    for key in sorted(set(target) - set(source)):
        drops.append(f"-- view: {key} (drop)\nDROP VIEW IF EXISTS {key};")

    for key in sorted(set(source) & set(target)):
        if source[key]["body"] != target[key]["body"]:
            modifies.append(f"-- view: {key} (modify)\n{source[key]['raw_ddl']}")

    return creates, modifies, drops


def diff_matviews(source, target):
    creates, modifies, drops = [], [], []

    for key in sorted(set(source) - set(target)):
        m = source[key]
        parts = [m["raw_ddl"]] + [stmt for _, stmt in m["indexes"]]
        creates.append(f"-- matview: {key} (create)\n" + "\n\n".join(parts))

    for key in sorted(set(target) - set(source)):
        drops.append(f"-- matview: {key} (drop)\nDROP MATERIALIZED VIEW IF EXISTS {key};")

    for key in sorted(set(source) & set(target)):
        s, t = source[key], target[key]
        if s["body"] != t["body"] or dict(s["indexes"]) != dict(t["indexes"]):
            parts = [f"DROP MATERIALIZED VIEW IF EXISTS {key};", s["raw_ddl"]]
            parts += [stmt for _, stmt in s["indexes"]]
            modifies.append(f"-- matview: {key} (rebuild required)\n" + "\n\n".join(parts))

    return creates, modifies, drops


def diff_sequences(source, target):
    creates, modifies, drops = [], [], []
    fields = ("data_type", "start", "increment", "minvalue", "maxvalue", "cache", "cycle")

    for key in sorted(set(source) - set(target)):
        ddl = build_sequence_ddl_from_parsed(key, source[key])
        creates.append(f"-- sequence: {key} (create)\n{ddl}")

    for key in sorted(set(target) - set(source)):
        drops.append(f"-- sequence: {key} (drop)\nDROP SEQUENCE IF EXISTS {key};")

    for key in sorted(set(source) & set(target)):
        s, t = source[key], target[key]
        if any(s[f] != t[f] for f in fields):
            ddl = build_sequence_ddl_from_parsed(key, s, keyword="ALTER SEQUENCE")
            modifies.append(f"-- sequence: {key} (modify)\n{ddl}")

    return creates, modifies, drops


def generate_diff(source_dir, target_dir):
    source = load_snapshot(source_dir)
    target = load_snapshot(target_dir)

    t_creates, t_modifies, t_drops = diff_tables(source["tables"], target["tables"])
    v_creates, v_modifies, v_drops = diff_views(source["views"], target["views"])
    m_creates, m_modifies, m_drops = diff_matviews(source["mviews"], target["mviews"])
    s_creates, s_modifies, s_drops = diff_sequences(source["sequences"], target["sequences"])

    return {
        "create": s_creates + t_creates + v_creates + m_creates,
        "modify": t_modifies + v_modifies + m_modifies + s_modifies,
        "drop": m_drops + v_drops + t_drops + s_drops,
    }


def write_output(output_dir, statements):
    os.makedirs(output_dir, exist_ok=True)
    paths = {}
    for kind in ("create", "modify", "drop"):
        content = "\n\n".join(statements[kind])
        if content:
            content += "\n"
        path = os.path.join(output_dir, f"{kind}.sql")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        paths[kind] = path
    return paths


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Compare two exported schema snapshots (as produced by export_schema.py) and "
            "generate SQL that, when run against a database currently matching --target, "
            "brings it in line with --source. Swap --source/--target to get the opposite "
            "direction."
        )
    )
    parser.add_argument("--source", required=True, help="Snapshot folder representing the desired end state")
    parser.add_argument("--target", required=True, help="Snapshot folder representing the state to be migrated")
    parser.add_argument("--output", required=True, help="Output folder for create.sql / modify.sql / drop.sql")
    args = parser.parse_args()

    print(f"Diffing: making '{args.target}' look like '{args.source}' ...")

    statements = generate_diff(args.source, args.target)
    paths = write_output(args.output, statements)

    total = 0
    for kind in ("create", "modify", "drop"):
        count = len(statements[kind])
        total += count
        print(f"  [{kind}] {count} statement(s) -> {paths[kind]}")

    print(f"\nDone. {total} statement(s) across 3 file(s).")


if __name__ == "__main__":
    main()
