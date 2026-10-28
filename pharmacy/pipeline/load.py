"""
load.py — Write the Pharmacy tables into Unity Catalog with the notebook's Spark
session (Databricks only; the dry run never gets here).

  1. Create missing tables. An existing table is never altered: a column the
     run needs but the table lacks stops the run before anything is written.
  2. bronze: INSERT (append-only; reruns add rows, never change or delete).
  3. silver, gold, restricted: MERGE on the table's key, so a rerun of the same
     round updates rows instead of adding duplicates.

Databricks has no transaction across tables. Each MERGE table's version is
noted first, and if a MERGE fails the tables already merged in this run are
RESTOREd. Bronze rows stay: they are the record of what was downloaded.

PRIMARY KEY / FOREIGN KEY constraints are informational in Databricks; the
checks in transform.py are what keep the keys clean.
"""

import logging

import pandas as pd

from .transform import ISSUES_TABLE, Table

logger = logging.getLogger(__name__)

TRY_CAST = ("INT", "BIGINT", "DOUBLE", "DATE", "TIMESTAMP", "TIMESTAMP_NTZ", "BOOLEAN")


def _q(name: str) -> str:
    return "`" + str(name).replace("`", "``") + "`"


def _cols(names) -> str:
    return ", ".join(_q(c) for c in names)


class Loader:
    def __init__(self, spark, catalog: str):
        self.spark = spark
        self.catalog = catalog

    def fq(self, schema: str, table: str) -> str:
        return f"{_q(self.catalog)}.{_q(schema)}.{_q(table)}"

    def _sql(self, statement: str):
        return self.spark.sql(statement)

    # ── Tables ───────────────────────────────────────────────────────────────

    def _existing_columns(self, schema: str, table: str) -> set[str] | None:
        rows = self._sql(
            f"SELECT column_name FROM {_q(self.catalog)}.information_schema.columns "
            f"WHERE table_schema = '{schema.lower()}' AND table_name = '{table.lower()}'"
        ).collect()
        return {r[0].lower() for r in rows} or None

    def ensure_table(self, t: Table) -> None:
        existing = self._existing_columns(t.schema, t.name)
        if existing is not None:
            missing = [c for c in t.df.columns if c.lower() not in existing]
            if missing:
                raise ValueError(
                    f"{t.schema}.{t.name} exists but has no column(s) {missing}. The pipeline never "
                    f"alters a table: add the columns, or fix map/pharmacy/gold_types.csv.")
            return
        cols = [f"{_q(c)} {t.types[c]}" + (" NOT NULL" if c in t.pk else "") for c in t.df.columns]
        if t.pk and not t.append:
            cols.append(f"CONSTRAINT {_q(t.name + '_pk')} PRIMARY KEY ({_cols(t.pk)})")
        if t.fk and t.parent:
            cols.append(f"CONSTRAINT {_q(t.name + '_fk')} FOREIGN KEY ({_cols(t.fk)}) "
                        f"REFERENCES {self.fq(t.parent_schema, t.parent)} ({_cols(t.parent_pk)})")
        self._sql(f"CREATE TABLE IF NOT EXISTS {self.fq(t.schema, t.name)} (\n  "
                  + ",\n  ".join(cols)
                  + "\n) TBLPROPERTIES ('delta.columnMapping.mode' = 'name')")
        logger.info(f"  Created {t.schema}.{t.name}")

    # ── Data ─────────────────────────────────────────────────────────────────

    def _view(self, t: Table) -> str:
        """The table's rows as a temporary view, columns c0..cN, all STRING, so
        any column name survives; _select renames and types them."""
        from pyspark.sql.types import StringType, StructField, StructType
        schema = StructType([StructField(f"c{i}", StringType(), True) for i in range(len(t.df.columns))])
        rows = [tuple(None if pd.isna(v) else str(v) for v in r) for r in t.df.itertuples(index=False, name=None)]
        view = f"pharmacy_{t.schema}_{t.name}_src"
        self.spark.createDataFrame(rows, schema).createOrReplaceTempView(view)
        return view

    def _select(self, t: Table, view: str) -> str:
        parts = []
        for i, c in enumerate(t.df.columns):
            typ = t.types[c]
            # Values were cleaned in transform.py; try_cast only guards against surprises
            expr = f"try_cast(c{i} AS {typ})" if typ in TRY_CAST else f"c{i}"
            parts.append(f"{expr} AS {_q(c)}")
        return f"SELECT {', '.join(parts)} FROM {view}"

    def insert(self, t: Table) -> None:
        view = self._view(t)
        self._sql(f"INSERT INTO {self.fq(t.schema, t.name)} ({_cols(t.df.columns)}) {self._select(t, view)}")
        logger.info(f"  Appended {len(t.df)} rows to {t.schema}.{t.name}")

    def merge(self, t: Table) -> None:
        view = self._view(t)
        on = " AND ".join(f"t.{_q(k)} = s.{_q(k)}" for k in t.pk)
        update = ", ".join(f"t.{_q(c)} = s.{_q(c)}" for c in t.df.columns if c not in t.pk)
        self._sql(
            f"MERGE INTO {self.fq(t.schema, t.name)} AS t USING ({self._select(t, view)}) AS s ON {on} "
            + (f"WHEN MATCHED THEN UPDATE SET {update} " if update else "")
            + f"WHEN NOT MATCHED THEN INSERT ({_cols(t.df.columns)}) "
            f"VALUES ({', '.join('s.' + _q(c) for c in t.df.columns)})")
        logger.info(f"  Merged {len(t.df)} rows into {t.schema}.{t.name}")

    def _version(self, t: Table) -> int:
        return int(self._sql(f"DESCRIBE HISTORY {self.fq(t.schema, t.name)} LIMIT 1").collect()[0][0])

    def load(self, tables: list[Table]) -> None:
        for t in tables:
            self.ensure_table(t)
        for t in tables:
            if t.append:
                self.insert(t)
        done: list[tuple[Table, int]] = []
        try:
            for t in tables:
                if not t.append:
                    before = self._version(t)
                    self.merge(t)
                    done.append((t, before))
        except Exception:
            logger.error("  MERGE failed — restoring the tables already merged in this run")
            for t, version in reversed(done):
                target = self.fq(t.schema, t.name)
                try:
                    self._sql(f"RESTORE TABLE {target} TO VERSION AS OF {version}")
                    logger.error(f"  Restored {t.schema}.{t.name} to version {version}")
                except Exception as e:
                    logger.error(f"  Could not restore {t.schema}.{t.name}: {e}. Run by hand: "
                                 f"RESTORE TABLE {target} TO VERSION AS OF {version}")
            raise

    def write_issues(self, issues: pd.DataFrame) -> None:
        """Append the run's validation issues to silver.pharmacy_validation_issues."""
        types = {c: "STRING" for c in issues.columns}
        types.update({"logged_at": "TIMESTAMP", "blocking": "BOOLEAN", "value_masked": "BOOLEAN"})
        t = Table("silver", "issues", ISSUES_TABLE, issues, types, append=True)
        self.ensure_table(t)
        self.insert(t)
