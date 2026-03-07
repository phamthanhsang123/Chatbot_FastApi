from sqlalchemy import text

def load_schema_text(engine, allowed_tables=None):
    query = """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
        ORDER BY table_name, ordinal_position
    """

    schema = {}

    with engine.connect() as conn:
        result = conn.execute(text(query))

        for row in result:
            table = row[0]
            column = row[1]
            dtype = row[2]

            if allowed_tables and table not in allowed_tables:
                continue

            schema.setdefault(table, []).append(f"{column} {dtype}")

    schema_text = ""
    for table, cols in schema.items():
        schema_text += f"{table}({', '.join(cols)})\n"

    return schema_text
