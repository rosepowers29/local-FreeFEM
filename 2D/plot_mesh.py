"""
plot_mesh.py
Reads mesh_vertices.csv / mesh_triangles.csv (produced by mesh_report.edp)
and renders region-colored mesh visualizations at three zoom levels.
Requires: numpy, matplotlib.

Usage:
    FreeFem++ -nw mesh_report.edp    # regenerates the CSVs from the current mesh
    python3 plot_mesh.py             # regenerates the PNGs from those CSVs
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.patches import Patch

verts = np.loadtxt("mesh_vertices.csv", delimiter=",", skiprows=1)
tris = np.loadtxt("mesh_triangles.csv", delimiter=",", skiprows=1).astype(int)

x = verts[:, 0] * 1000   # mm
y = verts[:, 1] * 1e6    # microns
v0, v1, v2, region = tris[:, 0], tris[:, 1], tris[:, 2], tris[:, 3]

region_names = {1: "Cu (bottom)", 2: "Ag (bottom)", 3: "Hastelloy", 4: "Buffer",
                5: "REBCO", 6: "Ag (top)", 7: "Cu (top)"}
colors = {1: "#B87333", 2: "#C0C0C0", 3: "#4B4B4B", 4: "#8B5A2B",
          5: "#2E8B57", 6: "#C0C0C0", 7: "#B87333"}
legend_elems = [Patch(facecolor=colors[r], label=f"{r}: {region_names[r]}") for r in range(1, 8)]


def build_polys(mask):
    idx = np.where(mask)[0]
    return np.stack([
        np.column_stack([x[v0[idx]], y[v0[idx]]]),
        np.column_stack([x[v1[idx]], y[v1[idx]]]),
        np.column_stack([x[v2[idx]], y[v2[idx]]]),
    ], axis=1)


def render(xlim, ylim, edgecolor, title, fname, figsize):
    fig, ax = plt.subplots(figsize=figsize)
    mask_zoom = (x[v0] >= xlim[0]) & (x[v0] <= xlim[1])
    for rid in range(1, 8):
        mask = (region == rid) & mask_zoom
        polys = build_polys(mask)
        pc = PolyCollection(polys, facecolor=colors[rid], edgecolor=edgecolor, linewidth=0.3)
        ax.add_collection(pc)
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_xlabel("length x [mm]")
    ax.set_ylabel("thickness y [um]  (NOT to scale vs x)")
    ax.set_title(title)
    ax.legend(handles=legend_elems, loc='center left', bbox_to_anchor=(1.0, 0.5), fontsize=8)
    fig.tight_layout()
    fig.savefig(fname, dpi=150)
    print(f"saved {fname}")


# full tape, region-colored (no wireframe -- too many elements to show cleanly)
render((0, 200), (0, 95), 'none',
       "Full tape mesh, 7 layers, colored by region (200mm x 95um, y-axis exaggerated)",
       "mesh_full_by_region.png", (13, 3.2))

# zoomed view showing individual mesh triangles
render((0, 6), (0, 95), 'black',
       "Zoomed view showing individual mesh triangles (wireframe), first 6mm",
       "mesh_zoom_wireframe.png", (11, 5))

# extreme zoom on the thin-layer stack
render((0, 3), (68, 78), 'black',
       "Extreme zoom: Hastelloy/Buffer/REBCO/Ag-top stack detail (first 3mm, y=68-78um)",
       "mesh_zoom_thinlayers.png", (11, 5))
