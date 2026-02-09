# Local-Citation-Network
A network mapper to local references in RTF
# RTF Internal Citation Network

Build a **directed citation network** **only among references contained in a single RTF bibliography**.

- **Nodes** = selected references from the RTF (e.g., `[1]..[N]`)
- **Edges** = `A → B` *only if* reference **A cites B**, and **both A and B are in your chosen set**
- **Publication sequence** is preserved via node attributes:
  - `pub_year`
  - `rtf_order`
- Exports:
  - `.graphml` for **Gephi / Cytoscape**
  - `_nodes.csv` and `_edges.csv` for inspection

Citation data source: **OpenAlex** (free).

> Note: This tool does **not** add any external papers to your network.

---

## Install

Python 3.9+ recommended.

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows (PowerShell)
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
