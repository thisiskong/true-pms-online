import argparse
import getpass
import os
import sys

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    sys.exit("psycopg2 is required. Install it with: pip install psycopg2-binary")


def get_tables(cur, schema, table_filter):
    cur.execute(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relkind IN ('r', 'p')
          AND c.relispartition = false
        ORDER BY c.relname
        """,
        (schema,),
    )
    rows = [r[0] for r in cur.fetchall()]
    if table_filter:
        wanted = {t.strip() for t in table_filter.split(",")}
        rows = [r for r in rows if r in wanted]
    return rows


def get_matviews(cur, schema, table_filter):
    cur.execute(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relkind = 'm'
        ORDER BY c.relname
        """,
        (schema,),
    )
    rows = [r[0] for r in cur.fetchall()]
    if table_filter:
        wanted = {t.strip() for t in table_filter.split(",")}
        rows = [r for r in rows if r in wanted]
    return rows


def get_sequences(cur, schema, table_filter):
    cur.execute(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relkind = 'S'
        ORDER BY c.relname
        """,
        (schema,),
    )
    rows = [r[0] for r in cur.fetchall()]
    if table_filter:
        wanted = {t.strip() for t in table_filter.split(",")}
        rows = [r for r in rows if r in wanted]
    return rows


def get_sequence_def(cur, schema, sequence):
    cur.execute(
        """
        SELECT data_type, start_value, min_value, max_value, increment_by, cycle, cache_size
        FROM pg_sequences
        WHERE schemaname = %s
          AND sequencename = %s
        """,
        (schema, sequence),
    )
    return cur.fetchone()


def get_columns(cur, schema, table):
    cur.execute(
        """
        SELECT
            a.attname,
            pg_catalog.format_type(a.atttypid, a.atttypmod),
            a.attnotnull,
            pg_get_expr(d.adbin, d.adrelid) AS default_val
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE n.nspname = %s
          AND c.relname = %s
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        (schema, table),
    )
    return cur.fetchall()


def get_constraints(cur, schema, table):
    cur.execute(
        """
        SELECT
            con.conname,
            con.contype,
            pg_get_constraintdef(con.oid, true)
        FROM pg_constraint con
        JOIN pg_class c ON c.oid = con.conrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relname = %s
        ORDER BY con.contype, con.conname
        """,
        (schema, table),
    )
    return cur.fetchall()


def get_partition_clause(cur, schema, table):
    cur.execute(
        """
        SELECT pg_get_partkeydef(c.oid)
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relname = %s
          AND c.relkind = 'p'
        """,
        (schema, table),
    )
    row = cur.fetchone()
    return row[0] if row else None


def get_indexes(cur, schema, table):
    cur.execute(
        """
        SELECT indexdef
        FROM pg_indexes
        WHERE schemaname = %s
          AND tablename = %s
          AND indexname NOT IN (
              SELECT conname
              FROM pg_constraint con
              JOIN pg_class c ON c.oid = con.conrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
              WHERE n.nspname = %s AND c.relname = %s
          )
        ORDER BY indexname
        """,
        (schema, table, schema, table),
    )
    return [r[0] for r in cur.fetchall()]


def get_views(cur, schema, table_filter):
    cur.execute(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relkind = 'v'
        ORDER BY c.relname
        """,
        (schema,),
    )
    rows = [r[0] for r in cur.fetchall()]
    if table_filter:
        wanted = {t.strip() for t in table_filter.split(",")}
        rows = [r for r in rows if r in wanted]
    return rows


def get_view_def(cur, schema, view):
    cur.execute(
        """
        SELECT pg_get_viewdef(c.oid, true)
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relname = %s
          AND c.relkind = 'v'
        """,
        (schema, view),
    )
    row = cur.fetchone()
    return row[0] if row else None


def get_matview_def(cur, schema, matview):
    cur.execute(
        """
        SELECT pg_get_viewdef(c.oid, true)
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relname = %s
          AND c.relkind = 'm'
        """,
        (schema, matview),
    )
    row = cur.fetchone()
    return row[0] if row else None


def build_ddl(schema, table, columns, constraints, partition_clause):
    col_defs = []
    for name, dtype, notnull, default in columns:
        col_def = f"    {name} {dtype}"
        if default is not None:
            col_def += f" DEFAULT {default}"
        if notnull:
            col_def += " NOT NULL"
        col_defs.append(col_def)

    con_defs = []
    for con_name, con_type, con_def in constraints:
        con_defs.append(f"    CONSTRAINT {con_name} {con_def}")

    body = ",\n".join(col_defs + con_defs)

    lines = [f"CREATE TABLE {schema}.{table} (", body]
    if partition_clause:
        lines.append(f") PARTITION BY {partition_clause};")
    else:
        lines.append(");")

    return "\n".join(lines)


def build_sequence_ddl(schema, sequence, sequence_def):
    data_type, start_value, min_value, max_value, increment_by, cycle, cache_size = sequence_def
    lines = [
        f"CREATE SEQUENCE {schema}.{sequence}",
        f"    AS {data_type}",
        f"    START WITH {start_value}",
        f"    INCREMENT BY {increment_by}",
        f"    MINVALUE {min_value}",
        f"    MAXVALUE {max_value}",
        f"    CACHE {cache_size}",
    ]
    lines.append("    CYCLE;" if cycle else "    NO CYCLE;")
    return "\n".join(lines)


def build_view_ddl(schema, view, view_def):
    return f"CREATE OR REPLACE VIEW {schema}.{view} AS\n{view_def};"


def build_matview_ddl(schema, matview, view_def):
    return f"CREATE MATERIALIZED VIEW {schema}.{matview} AS\n{view_def};"


def export_table(cur, schema, table, output_dir):
    columns = get_columns(cur, schema, table)
    constraints = get_constraints(cur, schema, table)
    partition_clause = get_partition_clause(cur, schema, table)
    indexes = get_indexes(cur, schema, table)

    ddl = build_ddl(schema, table, columns, constraints, partition_clause)

    parts = [ddl]
    for idx_def in indexes:
        parts.append(f"{idx_def};")

    content = "\n\n".join(parts) + "\n"

    filename = os.path.join(output_dir, f"{schema}.{table}.sql")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    return filename


def export_sequence(cur, schema, sequence, output_dir):
    sequence_def = get_sequence_def(cur, schema, sequence)
    ddl = build_sequence_ddl(schema, sequence, sequence_def)

    filename = os.path.join(output_dir, f"{schema}.{sequence}.sql")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(ddl + "\n")

    return filename


def export_view(cur, schema, view, output_dir):
    view_def = get_view_def(cur, schema, view)
    ddl = build_view_ddl(schema, view, view_def)

    filename = os.path.join(output_dir, f"{schema}.{view}.sql")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(ddl + "\n")

    return filename


def export_matview(cur, schema, matview, output_dir):
    view_def = get_matview_def(cur, schema, matview)
    indexes = get_indexes(cur, schema, matview)

    ddl = build_matview_ddl(schema, matview, view_def)

    parts = [ddl]
    for idx_def in indexes:
        parts.append(f"{idx_def};")

    content = "\n\n".join(parts) + "\n"

    filename = os.path.join(output_dir, f"{schema}.{matview}.sql")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    return filename


def main():
    parser = argparse.ArgumentParser(description="Export PostgreSQL table schemas to SQL files.")
    parser.add_argument("--host", default="localhost", help="Database host (default: localhost)")
    parser.add_argument("--port", type=int, default=5432, help="Database port (default: 5432)")
    parser.add_argument("--dbname", required=True, help="Database name")
    parser.add_argument("--user", required=True, help="Database user")
    parser.add_argument("--password", default=None, help="Database password (prompted if omitted)")
    parser.add_argument("--schema", default="public", help="Schema to export (default: public)")
    parser.add_argument("--tables", default=None, help="Comma-separated table/view/matview/sequence names (default: all)")
    parser.add_argument("--output", required=True, help="Output folder path")
    args = parser.parse_args()

    password = args.password or getpass.getpass(f"Password for {args.user}@{args.host}: ")

    tables_dir = os.path.join(args.output, "tables")
    views_dir = os.path.join(args.output, "views")
    mviews_dir = os.path.join(args.output, "mviews")
    sequences_dir = os.path.join(args.output, "sequences")
    os.makedirs(tables_dir, exist_ok=True)
    os.makedirs(views_dir, exist_ok=True)
    os.makedirs(mviews_dir, exist_ok=True)
    os.makedirs(sequences_dir, exist_ok=True)

    try:
        conn = psycopg2.connect(
            host=args.host,
            port=args.port,
            dbname=args.dbname,
            user=args.user,
            password=password,
        )
    except psycopg2.OperationalError as e:
        sys.exit(f"Connection failed: {e}")

    total = 0
    with conn:
        with conn.cursor() as cur:
            tables = get_tables(cur, args.schema, args.tables)
            views = get_views(cur, args.schema, args.tables)
            matviews = get_matviews(cur, args.schema, args.tables)
            sequences = get_sequences(cur, args.schema, args.tables)

            if not tables and not views and not matviews and not sequences:
                print("No tables, views, materialized views, or sequences found matching the given criteria.")
                return

            if tables:
                print(f"Exporting {len(tables)} table(s) to '{tables_dir}' ...")
                for table in tables:
                    filepath = export_table(cur, args.schema, table, tables_dir)
                    print(f"  [table]   {table:40s} -> {filepath}")
                    total += 1

            if views:
                print(f"Exporting {len(views)} view(s) to '{views_dir}' ...")
                for view in views:
                    filepath = export_view(cur, args.schema, view, views_dir)
                    print(f"  [view]    {view:40s} -> {filepath}")
                    total += 1

            if matviews:
                print(f"Exporting {len(matviews)} materialized view(s) to '{mviews_dir}' ...")
                for matview in matviews:
                    filepath = export_matview(cur, args.schema, matview, mviews_dir)
                    print(f"  [matview] {matview:40s} -> {filepath}")
                    total += 1

            if sequences:
                print(f"Exporting {len(sequences)} sequence(s) to '{sequences_dir}' ...")
                for sequence in sequences:
                    filepath = export_sequence(cur, args.schema, sequence, sequences_dir)
                    print(f"  [sequence]{sequence:40s} -> {filepath}")
                    total += 1

    conn.close()
    print(f"\nDone. {total} file(s) written.")


if __name__ == "__main__":
    main()
