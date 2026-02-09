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

## Folder Structure

Local-Citation-Network/
├─ src/
│ └─ map_rtf_internal_citations.py
├─ data/
│ ├─ input/ # place your RTF files here
│ └─ output/ # generated networks (gitignored)
├─ requirements.txt
└─ README.md

---

## Usage

### 1) Use all references in the RTF

```bash
python src/map_rtf_internal_citations.py \
  --rtf data/input/System Dynamics.rtf \
  --select all \
  --out-prefix data/output/network

### 2) Choose a range (example: refs 1–13)

python src/map_rtf_internal_citations.py \
  --rtf data/input/System Dynamics.rtf \
  --select 1-13 \
  --out-prefix data/output/network_1_13

### 3) Choose a custom set (example: 1,3,5–9,12)

python src/map_rtf_internal_citations.py \
  --rtf data/input/System Dynamics.rtf \
  --select 1,3,5-9,12 \
  --out-prefix data/output/network_custom

### Outputs

--out-prefix data/output/network_custom

## Visualizing the Network in Gephi

Gephi is recommended for exploring and styling the citation network.

### Steps

1. Install Gephi  
   https://gephi.org

2. Open Gephi → **File → Open** → select your generated `.graphml` file  
   (e.g., `data/output/network.graphml`)

3. Go to **Layout** and run:

   **ForceAtlas 2** (default settings are usually fine for small networks)

4. Style the graph:

   - Open **Appearance**
   - Set **Node Color** → `pub_year`
   - Set **Node Size** → **In-Degree** (papers cited most within your selected set)

### What this reveals

You will immediately see:

- **Foundational papers** (large nodes, high in-degree)
- **Bridges between themes** (high betweenness / central position)
- **Citation flow over time** (older → newer via color gradient)

This is especially useful for understanding methodological lineage and conceptual evolution inside your chosen bibliography.
