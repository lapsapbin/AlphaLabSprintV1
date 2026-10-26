"""Official snapshots, explicit monthly block parsing and deterministic CSV production.

All full-sample routines here are internal to the structural QC pipeline. Research
callers use access.load_research; this module does not authorize research access.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from functools import wraps
import hashlib
import io
import json
from pathlib import Path
import re
import urllib.request
from urllib.parse import urljoin, urlparse
import zipfile

import pandas as pd

from .validation import ContractError, require, validate_tables

PARSER_VERSION = "1.0.0"
BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/"
INDEX = BASE + "data_library.html"
FILES = {
    "industries": "49_Industry_Portfolios_CSV.zip",
    "ff3": "F-F_Research_Data_Factors_CSV.zip",
    "mom": "F-F_Momentum_Factor_CSV.zip",
}
MEMBERS = {key: name.replace("_CSV.zip", ".csv") for key, name in FILES.items()}


def _audited_qc(function):
    """Audit direct Python QC calls as well as CLI calls, including real tests."""
    @wraps(function)
    def run(root, *args, **kwargs):
        from .access import log_access
        log_access(root, "structural_qc", "BEGIN")
        try:
            result = function(root, *args, **kwargs)
        except Exception:
            log_access(root, "structural_qc", "FAIL")
            raise
        status = result.get("status", "PASS") if isinstance(result, dict) else "PASS"
        log_access(root, "structural_qc", status)
        return result
    return run


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(content, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_manifest(root: Path) -> dict:
    value = json.loads((root / "data/manifest.json").read_text())
    require(value["schema_version"] == 1, "manifest_schema")
    return value


def zip_text(payload: bytes, kind: str) -> tuple[str, str]:
    require(zipfile.is_zipfile(io.BytesIO(payload)), "expected_zip_not_html")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = archive.infolist()
            require(len(members) == 1, "unexpected_zip_members")
            member = members[0]
            require(member.filename.casefold() == MEMBERS[kind].casefold(), "unexpected_csv_member")
            require(member.file_size <= 20_000_000, "zip_size_limit")
            require(archive.testzip() is None, "zip_crc")
            return archive.read(member).decode("utf-8-sig"), member.filename
    except (zipfile.BadZipFile, UnicodeDecodeError, RuntimeError):
        raise ContractError("invalid_zip_or_csv_encoding") from None


def _normalize_title(line: str) -> str:
    return re.sub(r"[\s\-–—]+", " ", line.strip()).casefold()


def parse_monthly(text: str, kind: str) -> tuple[pd.DataFrame, dict]:
    """Identify a header + six-digit dates, never an unverified skiprows offset."""
    lines = text.splitlines()
    rows = [[cell.strip() for cell in row] for row in csv.reader(lines)]
    candidates = []
    for i, row in enumerate(rows):
        if len(row) < 2 or row[0] != "":
            continue
        previous = next((lines[j].strip() for j in range(i - 1, -1, -1) if lines[j].strip()), "")
        if kind == "industries":
            if _normalize_title(previous) != "average value weighted returns monthly":
                continue
        elif row[1:] != ({"ff3": ["Mkt-RF", "SMB", "HML", "RF"], "mom": ["Mom"]}[kind]):
            continue
        first = i + 1
        while first < len(rows) and not any(rows[first]):
            first += 1
        if first < len(rows) and re.fullmatch(r"\d{6}", rows[first][0]):
            candidates.append((i, first, previous))
    require(len(candidates) == 1, "exactly_one_matching_monthly_block")
    header, first, title = candidates[0]
    labels = rows[header][1:]
    require(all(labels) and len(labels) == len(set(labels)), "duplicate_or_empty_columns")
    dates, values = [], []
    for row in rows[first:]:
        if not any(row):
            break
        require(bool(re.fullmatch(r"\d{6}", row[0])), "unexpected_row_in_monthly_block")
        require(len(row) == len(labels) + 1, "monthly_row_width_or_label_change")
        try:
            date = pd.Period(f"{row[0][:4]}-{row[0][4:]}", freq="M")
            # Detect sentinel in raw percentage units before the single division.
            raw = [float(value) if value else float("nan") for value in row[1:]]
        except (ValueError, OverflowError):
            raise ContractError("invalid_month_or_numeric_encoding") from None
        dates.append(date)
        values.append([float("nan") if value in (-99.99, -999.0) else value / 100 for value in raw])
    require(bool(dates), "empty_monthly_block")
    frame = pd.DataFrame(values, index=pd.PeriodIndex(dates, freq="M", name="month"), columns=labels, dtype="float64")
    require(not frame.index.has_duplicates, "duplicate_months")
    require(frame.index.is_monotonic_increasing, "unsorted_months")
    # Earlier EW/annual blocks are possible. Never copy their observations into
    # metadata; retain only the source preamble before the first CSV header.
    preamble_end = next((i for i, row in enumerate(rows) if len(row) > 1 and row[0] == ""), header)
    metadata = {
        "parser_version": PARSER_VERSION,
        "block": title if kind == "industries" else "Monthly " + "/".join(labels),
        "header_line_1_based": header + 1,
        "columns": labels, "input_unit": "percent", "output_unit": "decimal_return",
        "scale_divisions": 1, "monthly_range": [str(frame.index.min()), str(frame.index.max())],
        "monthly_rows": len(frame), "description": lines[:preamble_end],
    }
    return frame, metadata


def _http(url: str) -> tuple[bytes, dict]:
    with urllib.request.urlopen(url, timeout=40) as response:
        require(response.status == 200, "http_status")
        require(urlparse(response.url).hostname == "mba.tuck.dartmouth.edu", "official_host_required")
        return response.read(20_000_001), {"http_status": response.status,
                                        "final_url": response.url,
                                        "content_type": response.headers.get("Content-Type"),
                                        "downloaded_at_utc": utc_now()}


def verify_raw(root: Path, manifest: dict) -> None:
    require(set(manifest["files"]) == set(FILES), "manifest_three_sources")
    for key, name in FILES.items():
        record = manifest["files"][key]
        require(record["filename"] == name, "manifest_filename")
        path = root / "data/raw" / name
        require(path.is_file(), "missing_raw_cache_use_manual_import")
        payload = path.read_bytes()
        require(len(payload) == record["bytes"] and sha256(payload) == record["sha256"], "raw_hash_mismatch")
        zip_text(payload, key)


@_audited_qc
def acquire(root: Path, import_dir: Path | None = None) -> dict:
    """Existing snapshot always uses hashes, never silently refreshes the network."""
    manifest_path = root / "data/manifest.json"
    if manifest_path.exists():
        manifest = read_manifest(root)
        if import_dir is not None:
            for key, name in FILES.items():
                destination = root / "data/raw" / name
                if not destination.exists():
                    payload = (import_dir / name).read_bytes()
                    require(sha256(payload) == manifest["files"][key]["sha256"], "import_hash_mismatch")
                    zip_text(payload, key)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with destination.open("xb") as handle:
                        handle.write(payload)
        verify_raw(root, manifest)
        return {"status": "PASS", "mode": "verified_cached_snapshot", "files": len(FILES)}
    require(not any((root / "data/raw" / name).exists() for name in FILES.values()), "unmanifested_raw_refuse_overwrite")
    if import_dir is None:
        page, page_http = _http(INDEX)
        html = page.decode("utf-8", errors="replace")
        links = {urljoin(INDEX, link) for link in re.findall(r'''href\s*=\s*["']([^"']+)''', html, flags=re.I)}
        for name in FILES.values():
            require(BASE + "ftp/" + name in links, "download_link_not_in_official_index")
        index_meta = {"official_index_sha256": sha256(page), "official_index_checked_at_utc": page_http["downloaded_at_utc"]}
    else:
        index_meta = {"official_index_checked_at_utc": None}
    manifest = {"schema_version": 1, "parser_version": PARSER_VERSION, "official_index": INDEX, "files": {}, **index_meta}
    pending = {}
    for key, name in FILES.items():
        url = BASE + "ftp/" + name
        if import_dir is None:
            payload, transfer = _http(url)
            method = "direct official HTTPS; verified link from official index"
        else:
            payload = (import_dir / name).read_bytes()
            transfer = {"imported_at_utc": utc_now(), "downloaded_at_utc": None, "http_status": None}
            method = "manual import; official source declared; original download time/HTTP not independently observed"
        body, member = zip_text(payload, key)
        _, parsed = parse_monthly(body, key)
        manifest["files"][key] = {"filename": name, "source_url": url, "bytes": len(payload),
                                 "sha256": sha256(payload), "zip_member": member, "method": method,
                                 "parser_version": PARSER_VERSION, "description": parsed["description"], **transfer}
        pending[name] = payload
    for name, payload in pending.items():
        target = root / "data/raw" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(payload)
    write_json(manifest_path, manifest)
    return {"status": "PASS", "mode": "new_snapshot", "files": len(FILES)}


@_audited_qc
def parse_snapshot_for_qc(root: Path, config: dict) -> tuple[dict, dict]:
    manifest = read_manifest(root)
    verify_raw(root, manifest)
    frames, metadata = {}, {}
    for kind, name in FILES.items():
        body, _ = zip_text((root / "data/raw" / name).read_bytes(), kind)
        full, parsed = parse_monthly(body, kind)
        frames[kind] = full.loc[(full.index >= config["data"]["start"]) & (full.index <= config["data"]["end"])].copy()
        metadata[kind] = parsed
    return frames, metadata


def csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, float_format="%.12g", lineterminator="\n").encode("utf-8")


def build(root: Path, config: dict) -> dict:
    frames, parsed = parse_snapshot_for_qc(root, config)
    qc = validate_tables(frames["industries"], frames["ff3"], frames["mom"], config)
    if qc["status"] != "PASS":
        return qc
    manifest = read_manifest(root)
    products, payloads = {}, {}
    for partition, (start, end) in config["partitions"].items():
        ind = frames["industries"].loc[start:end].copy()
        factors = frames["ff3"].join(frames["mom"], validate="one_to_one").loc[start:end].copy()
        ind.index = ind.index.astype(str)
        factors.index = factors.index.astype(str)
        long = ind.reset_index().melt(id_vars="month", var_name="industry", value_name="return")
        long = long.sort_values(["month", "industry"], kind="stable").reset_index(drop=True)
        for name, table in [("industry_returns", long), ("factors", factors.reset_index())]:
            relative = f"data/processed/{partition}/{name}.csv"
            payload = csv_bytes(table)
            products[relative] = {"sha256": sha256(payload), "bytes": len(payload), "rows": len(table),
                                  "range": [start, end], "columns": list(table.columns), "unit": "decimal_return"}
            payloads[relative] = payload
    if "products" in manifest:
        require(manifest["products"] == products, "reproduction_products_mismatch")
        require(manifest["parsing"] == parsed, "reproduction_parser_metadata_mismatch")
    # Preflight every existing artifact before any writes; refuse changed files.
    for relative, payload in payloads.items():
        path = root / relative
        require(not path.exists() or path.read_bytes() == payload, "existing_processed_content_mismatch")
    for relative, payload in payloads.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with path.open("xb") as handle:
                handle.write(payload)
    manifest.update({"parser_version": PARSER_VERSION, "parsing": parsed, "products": products})
    write_json(root / "data/manifest.json", manifest)
    return qc


def read_product(root: Path, partition: str, name: str, manifest: dict) -> pd.DataFrame:
    relative = f"data/processed/{partition}/{name}.csv"
    require(relative in manifest.get("products", {}), "missing_product_manifest")
    payload = (root / relative).read_bytes()
    require(sha256(payload) == manifest["products"][relative]["sha256"], "processed_hash_mismatch")
    try:
        frame = pd.read_csv(io.BytesIO(payload))
        frame["month"] = pd.PeriodIndex(frame["month"], freq="M")
        for col in (["return"] if name == "industry_returns" else ["Mkt-RF", "SMB", "HML", "RF", "Mom"]):
            frame[col] = pd.to_numeric(frame[col], errors="raise").astype("float64")
    except (ValueError, KeyError):
        raise ContractError("processed_schema_or_numeric_encoding") from None
    return frame


@_audited_qc
def validate_processed(root: Path, config: dict) -> dict:
    manifest = read_manifest(root)
    all_ind, all_factors = [], []
    for partition, (lo, hi) in sorted(config["partitions"].items(), key=lambda item: item[1][0]):
        industries = read_product(root, partition, "industry_returns", manifest)
        factors = read_product(root, partition, "factors", manifest)
        # Check each input file before concatenation; never sort away corruption.
        require(not industries.duplicated(["month", "industry"]).any(), "duplicate_month_industry")
        keys = industries[["month", "industry"]]
        require(keys.equals(keys.sort_values(["month", "industry"]).reset_index(drop=True)), "unsorted_long_form")
        require(not factors["month"].duplicated().any(), "duplicate_factor_months")
        require(factors["month"].is_monotonic_increasing, "unsorted_factor_months")
        for table in (industries, factors):
            require(table["month"].between(pd.Period(lo, "M"), pd.Period(hi, "M")).all(), "partition_date_boundary")
        all_ind.append(industries)
        all_factors.append(factors)
    long = pd.concat(all_ind, ignore_index=True)
    require(not long.duplicated(["month", "industry"]).any(), "duplicate_month_industry")
    require(long[["month", "industry"]].equals(long[["month", "industry"]].sort_values(["month", "industry"]).reset_index(drop=True)), "unsorted_long_form")
    require(set(long["industry"]) == set(config["data"]["labels"]), "changed_industry_labels")
    ind = long.pivot(index="month", columns="industry", values="return").reindex(columns=config["data"]["labels"])
    factors = pd.concat(all_factors, ignore_index=True).set_index("month")
    return validate_tables(ind, factors[["Mkt-RF", "SMB", "HML", "RF"]], factors[["Mom"]], config)
