#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd
import requests
import networkx as nx


OPENALEX_BASE = "https://api.openalex.org"
USER_AGENT = "rtf-internal-citation-mapper/1.0"


# -------------------- RTF parsing helpers --------------------
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s,;]+)", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def rtf_to_text(rtf: str) -> str:
    """Minimal RTF->text conversion good for numbered bibliographies."""
    def uni_repl(m):
        code = int(m.group(1))
        if code < 0:
            code = 65536 + code
        return chr(code)

    s = re.sub(r"\\u(-?\d+)\??", uni_repl, rtf)
    s = re.sub(r"\\'[0-9a-fA-F]{2}", "", s)                # hex escapes
    s = re.sub(r"\\[a-zA-Z]+\d* ?", "", s)                 # control words
    s = s.replace("{", "").replace("}", "")                # braces
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s+", "\n", s)
    return s.strip()


def split_numbered_refs(text: str) -> List[Tuple[int, str]]:
    """
    Extract blocks like:
    [1] ... \n\n [2] ...
    Works with common BibTeX-export RTF styles.
    """
    pattern = re.compile(r"\[(\d+)\](.*?)(?=\n\\\n\[\d+\]|\n\[\d+\]|$)", re.S)
    out = []
    for m in pattern.finditer(text):
        out.append((int(m.group(1)), m.group(2).strip()))
    return out


def extract_doi(s: str) -> Optional[str]:
    m = DOI_RE.search(s)
    return m.group(1).rstrip(".").lower() if m else None


def extract_title(s: str) -> str:
    m = re.search(r"“([^”]+)”", s)
    if m:
        return m.group(1).strip()
    m = re.search(r"\"([^\"]+)\"", s)
    if m:
        return m.group(1).strip()
    return s[:160].strip()


def extract_pub_year(s: str) -> Optional[int]:
    # ignore “Accessed:” section if present (web resources)
    cut = s.split("Accessed:")[0]
    years = [int(m.group(0)) for m in YEAR_RE.finditer(cut)]
    return years[-1] if years else None


# -------------------- Selection parsing --------------------
def parse_selection(selection: str, available_ref_nos: Set[int]) -> List[int]:
    """
    selection examples:
      "all"
      "1-13"
      "1,3,5-9,12"
    """
    selection = selection.strip().lower()
    if selection == "all":
        return sorted(available_ref_nos)

    chosen: Set[int] = set()
    parts = [p.strip() for p in selection.split(",") if p.strip()]
    for p in parts:
        if "-" in p:
            a, b = p.split("-", 1)
            a_i, b_i = int(a), int(b)
            lo, hi = min(a_i, b_i), max(a_i, b_i)
            for x in range(lo, hi + 1):
                if x in available_ref_nos:
                    chosen.add(x)
        else:
            x = int(p)
            if x in available_ref_nos:
                chosen.add(x)

    if not chosen:
        raise ValueError("Selection matched no references in the RTF.")
    return sorted(chosen)


# -------------------- OpenAlex helpers --------------------
@dataclass
class OAWork:
    id: str
    title: str
    year: Optional[int]
    doi: str
    referenced_works: List[str]


def oa_get_json(url: str, params: Optional[dict], sleep_s: float, retries: int = 4) -> Optional[dict]:
    backoff = 1.0
    for _ in range(retries):
        time.sleep(sleep_s)
        try:
            r = requests.get(url, params=params, timeout=30, headers={"User-Agent": USER_AGENT})
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(backoff)
                backoff *= 2
                continue
            return None
        except requests.RequestException:
            time.sleep(backoff)
            backoff *= 2
    return None


def oa_work_by_doi(doi: str, sleep_s: float) -> Optional[dict]:
    url = f"{OPENALEX_BASE}/works/https://doi.org/{doi}"
    return oa_get_json(
        url,
        params={"select": "id,display_name,publication_year,doi,referenced_works"},
        sleep_s=sleep_s,
    )


def oa_search_by_title_year(title: str, year: Optional[int], sleep_s: float) -> Optional[dict]:
    url = f"{OPENALEX_BASE}/works"
    params = {
        "search": title,
        "per-page": 5,
        "select": "id,display_name,publication_year,doi,referenced_works",
    }
    filters = []
    if year:
        filters.append(f"from_publication_date:{year}-01-01")
        filters.append(f"to_publication_date:{year}-12-31")
    if filters:
        params["filter"] = ",".join(filters)

    return oa_get_json(url, params=params, sleep_s=sleep_s)


def normalize_oa(w: dict) -> OAWork:
    return OAWork(
        id=w.get("id", ""),
        title=w.get("display_name", "") or "",
        year=w.get("publication_year", None),
        doi=(w.get("doi") or "").replace("https://doi.org/", "").lower() if w.get("doi") else "",
        referenced_works=w.get("referenced_works") or [],
    )


# -------------------- Build internal-only citation network --------------------
def main():
    ap = argparse.ArgumentParser(description="Build internal-only citation network among chosen refs in an RTF bibliography.")
    ap.add_argument("--rtf", required=True, help="Path to RTF file")
    ap.add_argument("--select", default="all", help='Refs to include: "all" or e.g. "1-13" or "1,3,5-9"')
    ap.add_argument("--out-prefix", default="network", help="Output file prefix")
    ap.add_argument("--sleep", type=float, default=0.15, help="Sleep between API calls (seconds)")
    args = ap.parse_args()

    rtf = open(args.rtf, "r", errors="ignore").read()
    txt = rtf_to_text(rtf)
    refs = split_numbered_refs(txt)

    if not refs:
        raise SystemExit("No numbered references like [1] ... found in the RTF.")

    ref_map = {n: raw for n, raw in refs}
    available = set(ref_map.keys())

    chosen_ref_nos = parse_selection(args.select, available)

    # Extract metadata for chosen refs
    rows = []
    for ref_no in chosen_ref_nos:
        raw = ref_map[ref_no]
        rows.append(
            {
                "ref_no": ref_no,
                "rtf_order": ref_no,  # RTF numbering is order
                "raw": raw,
                "doi": extract_doi(raw),
                "title": extract_title(raw),
                "pub_year_guess": extract_pub_year(raw),
            }
        )

    # Resolve each chosen ref to OpenAlex work (when possible)
    resolved: Dict[int, OAWork] = {}
    unresolved: List[int] = []

    for r in rows:
        ref_no = r["ref_no"]
        w = None

        if r["doi"]:
            data = oa_work_by_doi(r["doi"], sleep_s=args.sleep)
            if data:
                w = normalize_oa(data)

        if w is None:
            sr = oa_search_by_title_year(r["title"], r["pub_year_guess"], sleep_s=args.sleep)
            if sr and sr.get("results"):
                w = normalize_oa(sr["results"][0])

        if w is None or not w.id:
            unresolved.append(ref_no)
        else:
            resolved[ref_no] = w

    # Graph: ONLY chosen refs as nodes; ONLY edges between chosen refs
    G = nx.DiGraph()

    # Create stable node ids:
    # - Use OpenAlex ID when resolved
    # - Otherwise fall back to "UNRESOLVED_REF_{ref_no}" to keep the node in the graph
    node_id_by_ref: Dict[int, str] = {}
    for r in rows:
        ref_no = r["ref_no"]
        w = resolved.get(ref_no)
        node_id_by_ref[ref_no] = w.id if w else f"UNRESOLVED_REF_{ref_no}"

    # Reverse map for membership checks
    ref_by_node_id = {nid: ref for ref, nid in node_id_by_ref.items()}
    allowed_node_ids = set(ref_by_node_id.keys())

    # Add nodes with attributes
    for r in rows:
        ref_no = r["ref_no"]
        nid = node_id_by_ref[ref_no]
        w = resolved.get(ref_no)

        pub_year = (w.year if (w and w.year) else r["pub_year_guess"]) or ""
        title = (w.title if (w and w.title) else r["title"]) or ""
        doi = (w.doi if (w and w.doi) else (r["doi"] or "")) or ""

        G.add_node(
            nid,
            ref_no=ref_no,
            rtf_order=r["rtf_order"],
            pub_year=pub_year,
            doi=doi,
            title=title,
        )

    # Add edges: A -> B if A references B and both are in chosen set
    edges_rows = []
    for ref_no, w in resolved.items():
        src = node_id_by_ref[ref_no]
        for tgt in w.referenced_works:
            if tgt in allowed_node_ids:
                G.add_edge(src, tgt)
                edges_rows.append(
                    {
                        "citing_ref_no": ref_by_node_id[src],
                        "cited_ref_no": ref_by_node_id[tgt],
                    }
                )

    # Export
    out_graphml = f"{args.out_prefix}.graphml"
    out_nodes = f"{args.out_prefix}_nodes.csv"
    out_edges = f"{args.out_prefix}_edges.csv"

    nx.write_graphml(G, out_graphml)

    nodes_df = pd.DataFrame(
        [
            {
                "node_id": nid,
                "ref_no": d.get("ref_no"),
                "rtf_order": d.get("rtf_order"),
                "pub_year": d.get("pub_year"),
                "doi": d.get("doi"),
                "title": d.get("title"),
            }
            for nid, d in G.nodes(data=True)
        ]
    )

    edges_df = pd.DataFrame(edges_rows) if edges_rows else pd.DataFrame(columns=["citing_ref_no", "cited_ref_no"])

    # Sort nodes by time then RTF order
    def safe_int(x):
        try:
            return int(x)
        except Exception:
            return 999999

    nodes_df["pub_year_sort"] = nodes_df["pub_year"].apply(safe_int)
    nodes_df = nodes_df.sort_values(["pub_year_sort", "rtf_order"]).drop(columns=["pub_year_sort"])

    nodes_df.to_csv(out_nodes, index=False)
    edges_df.to_csv(out_edges, index=False)

    # Time-order check (citations should generally go later -> earlier)
    year_by_ref = {r["ref_no"]: r["pub_year_guess"] for r in rows}
    for ref_no, w in resolved.items():
        if w.year:
            year_by_ref[ref_no] = w.year

    violations = []
    for _, e in edges_df.iterrows():
        a, b = int(e["citing_ref_no"]), int(e["cited_ref_no"])
        ya, yb = year_by_ref.get(a), year_by_ref.get(b)
        if ya and yb and ya < yb:
            violations.append((a, b, ya, yb))

    print(f"RTF refs found: {len(refs)} | chosen: {len(chosen_ref_nos)}")
    print(f"Resolved in OpenAlex: {len(resolved)}/{len(chosen_ref_nos)}")
    if unresolved:
        print(f"[WARN] Unresolved refs (kept as nodes, but no edges from them): {unresolved}")

    print(f"Nodes: {G.number_of_nodes()} | Internal edges: {G.number_of_edges()}")
    print(f"Wrote: {out_graphml}")
    print(f"Wrote: {out_nodes}")
    print(f"Wrote: {out_edges}")

    if violations:
        print("\n[NOTE] Time-order violations (earlier paper citing later paper):")
        for a, b, ya, yb in violations:
            print(f"  Ref[{a}] ({ya}) cites Ref[{b}] ({yb})")
    else:
        print("\nNo time-order violations found among internal citations.")


if __name__ == "__main__":
    main()
