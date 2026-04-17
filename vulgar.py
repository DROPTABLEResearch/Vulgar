from __future__ import annotations

import argparse
import datetime as dt
import html
import sqlite3
import sys
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path


DB_PATH = "private/var/mobile/library/keyboard/VulgarWordUsage.db"
LOCAL_DB_NAME = "VulgarWordUsage.db"
APPLE_EPOCH = dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract VulgarWordUsage.db from an iOS full file system ZIP and "
            "build an HTML report grouped by vulgar word."
        )
    )
    parser.add_argument(
        "zip_file",
        nargs="?",
        help="Path to the iOS extraction ZIP. If omitted, the script uses the first .zip in the current directory.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output HTML path. Defaults to vulgar_word_usage_report.html in the current directory.",
    )
    return parser.parse_args()


def find_zip(zip_arg: str | None) -> Path:
    if zip_arg:
        zip_path = Path(zip_arg).expanduser().resolve()
        if not zip_path.is_file():
            raise FileNotFoundError(f"ZIP file not found: {zip_path}")
        return zip_path

    zip_files = sorted(Path.cwd().glob("*.zip"))
    if not zip_files:
        raise FileNotFoundError("No .zip files were found in the current directory.")
    if len(zip_files) > 1:
        print(
            f"Multiple ZIP files found. Using the first one alphabetically: {zip_files[0].name}",
            file=sys.stderr,
        )
    return zip_files[0].resolve()


def find_db_member(zf: zipfile.ZipFile) -> str:
    target = DB_PATH.casefold()
    for member in zf.namelist():
        normalized = member.lstrip("/").replace("\\", "/").casefold()
        if normalized == target:
            return member
    raise FileNotFoundError(
        f"Could not find {DB_PATH} inside the ZIP archive."
    )


def find_local_db() -> Path | None:
    local_db = Path.cwd() / LOCAL_DB_NAME
    if local_db.is_file():
        return local_db.resolve()
    return None


def apple_time_to_utc(timestamp: object) -> str:
    if timestamp in (None, ""):
        return "Unknown timestamp"

    try:
        seconds = float(timestamp)
    except (TypeError, ValueError):
        return f"Unrecognized timestamp: {timestamp}"

    converted = APPLE_EPOCH + dt.timedelta(seconds=seconds)
    return converted.strftime("%Y-%m-%d %H:%M:%S UTC")


def choose_output_path(requested_output: str | None) -> Path:
    if requested_output:
        base_path = Path(requested_output).expanduser().resolve()
    else:
        base_path = (Path.cwd() / "VulgarWordUsage Report.html").resolve()

    if not base_path.exists():
        return base_path

    stem = base_path.stem
    suffix = base_path.suffix
    parent = base_path.parent

    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def query_rows_from_db(db_path: Path) -> list[dict[str, object]]:
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row

    try:
        cursor = connection.execute(
            """
            SELECT app, vword, recipient, usage_count, last_use_timestamp
            FROM vword_usage
            ORDER BY LOWER(vword), LOWER(app), last_use_timestamp
            """
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        connection.close()


def extract_rows_from_zip(zip_path: Path) -> list[dict[str, object]]:
    with zipfile.ZipFile(zip_path, "r") as zf:
        db_member = find_db_member(zf)
        db_bytes = zf.read(db_member)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_db_path = Path(temp_dir) / "VulgarWordUsage.db"
        temp_db_path.write_bytes(db_bytes)
        return query_rows_from_db(temp_db_path)


def build_html(rows: list[dict[str, object]], source_zip: Path) -> str:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        vword = str(row.get("vword") or "[blank]")
        grouped[vword].append(row)

    sections: list[str] = []
    for vword in sorted(grouped, key=str.casefold):
        items: list[str] = []
        total_usage_count = 0
        for row in grouped[vword]:
            app = html.escape(str(row.get("app") or "[unknown app]"))
            raw_usage_count = row.get("usage_count")
            usage_count = html.escape(str(raw_usage_count or "0"))
            timestamp = html.escape(apple_time_to_utc(row.get("last_use_timestamp")))
            recipient = row.get("recipient")

            try:
                total_usage_count += int(raw_usage_count or 0)
            except (TypeError, ValueError):
                pass

            line = f"{app} - {timestamp}"
            if recipient not in (None, ""):
                line += f" ({html.escape(str(recipient))})"
            line += f" [Count: {usage_count}]"
            items.append(f"<li>{line}</li>")

        sections.append(
            (
                "<section class=\"word-group\">"
                "<div class=\"word-header\">"
                f"<h2>{html.escape(vword)}</h2>"
                f"<span class=\"total-count\">{total_usage_count}</span>"
                "</div>"
                "<ul>"
                f"{''.join(items)}"
                "</ul>"
                "</section>"
            )
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vulgar Word Usage Report</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #eef3f8;
      --panel: #ffffff;
      --panel-alt: #f7f9fc;
      --text: #1f2937;
      --muted: #5f6b7a;
      --border: #cfd8e3;
      --accent: #355c7d;
      --accent-soft: #e5eef8;
      --rule: #dfe6ee;
      --shadow: 0 10px 24px rgba(28, 44, 64, 0.08);
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
      color: var(--text);
      background: linear-gradient(180deg, #e8eef6 0%, var(--bg) 100%);
      min-height: 100vh;
    }}
    main {{
      max-width: 1080px;
      margin: 0 auto;
      padding: 28px 20px 48px;
    }}
    .hero {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-left: 6px solid var(--accent);
      border-radius: 8px;
      padding: 24px 26px;
      box-shadow: var(--shadow);
      margin-bottom: 18px;
      background-image: linear-gradient(90deg, rgba(53, 92, 125, 0.06), rgba(255, 255, 255, 0));
    }}
    .hero h1 {{
      margin: 0 0 10px;
      font-size: 2rem;
      letter-spacing: -0.02em;
      color: #111827;
    }}
    .hero p {{
      margin: 0;
      line-height: 1.6;
      color: var(--muted);
    }}
    .meta-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 12px;
      margin-bottom: 22px;
    }}
    .meta-card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px 18px;
      box-shadow: var(--shadow);
      background-image: linear-gradient(180deg, rgba(229, 238, 248, 0.55), rgba(255, 255, 255, 0));
    }}
    .meta-label {{
      display: block;
      font-size: 0.76rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 8px;
    }}
    .meta-value {{
      font-size: 1rem;
      font-weight: 600;
      word-break: break-word;
    }}
    .report-grid {{
      display: block;
    }}
    .word-group {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      box-shadow: var(--shadow);
      border-top: 3px solid #88a9c3;
    }}
    .word-group + .word-group {{
      margin-top: 14px;
    }}
    .word-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--rule);
    }}
    .word-header h2 {{
      margin: 0;
      font-size: 1.08rem;
      line-height: 1.3;
      word-break: break-word;
      font-family: Georgia, "Times New Roman", serif;
      font-weight: 700;
      color: #27445d;
    }}
    .total-count {{
      flex-shrink: 0;
      background: var(--accent-soft);
      color: var(--accent);
      border: 1px solid #c2d3e3;
      border-radius: 4px;
      padding: 5px 9px;
      font-size: 0.84rem;
      font-weight: 700;
    }}
    ul {{
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 8px;
    }}
    li {{
      background: var(--panel-alt);
      border: 1px solid var(--rule);
      border-left: 3px solid #bfd0df;
      border-radius: 6px;
      padding: 10px 12px;
      line-height: 1.5;
    }}
    code {{
      font-family: Consolas, "SFMono-Regular", monospace;
      background: #eef2f7;
      padding: 0.15em 0.4em;
      border-radius: 0.25em;
    }}
    .muted {{
      color: var(--muted);
    }}
    .empty-state {{
      text-align: center;
      padding: 28px;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }}
    @media (max-width: 640px) {{
      main {{
        padding: 24px 14px 40px;
      }}
      .hero {{
        padding: 20px 18px;
      }}
      .word-header {{
        align-items: flex-start;
        flex-direction: column;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <h1>Vulgar Word Usage Report</h1>
      <p><strong>Source file:</strong> {html.escape(str(source_zip.resolve()))}</p>
    </section>

    <section class="report-grid">
      {''.join(sections) if sections else '<div class="empty-state"><p>No rows found in <code>vword_usage</code>.</p></div>'}
    </section>
  </main>
</body>
</html>
"""


def main() -> int:
    args = parse_args()

    try:
        local_db_path = find_local_db()
        if local_db_path:
            rows = query_rows_from_db(local_db_path)
            source_path = local_db_path
        else:
            zip_path = find_zip(args.zip_file)
            rows = extract_rows_from_zip(zip_path)
            source_path = zip_path
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output_path = choose_output_path(args.output)

    html_report = build_html(rows, source_path)
    output_path.write_text(html_report, encoding="utf-8")

    print(f"Report written to: {output_path}")
    print(f"Rows processed: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
