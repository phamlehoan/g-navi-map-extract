#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build accel sidecars từ routing_meta.bin:

  routing_alt.bin  — ALT landmarks (GALT)
  routing_ch.bin   — Contraction Hierarchies upward (GNCH) [DISABLED - unstable]
  routing_crp.bin  — CRP-lite portals (GCRP) [DISABLED - not implemented]

NOTE: CH/CRP disabled vì không stable và không cần thiết cho Android memory-constrained.
ALT landmarks đủ cho long-haul routing performance.

  python build_routing_accel.py path/to/region_dir
  python build_routing_accel.py path/to/region_dir --landmarks 12
"""
from __future__ import print_function

import argparse
import heapq
import os
import struct
import sys
import time

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from routing.format import CLASS_COST, haversine_m


def read_u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def read_i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def parse_meta(path):
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 64 or data[0:4] != b"GNR1" or data[4] != 2:
        raise SystemExit("Need GNR1 v2 meta: %s" % path)
    n = read_u32(data, 8)
    e = read_u32(data, 12)
    nodes_off = read_u32(data, 16)
    edges_off = read_u32(data, 20)
    adj_off = read_u32(data, 24)
    nodes = []
    for i in range(n):
        o = nodes_off + i * 8
        la = read_i32(data, o) / 1e7
        lo = read_i32(data, o + 4) / 1e7
        nodes.append((la, lo))
    adj = [read_u32(data, adj_off + i * 4) for i in range(n + 1)]
    edges = []  # (to, len, flags)
    for i in range(e):
        o = edges_off + i * 8
        to = read_u32(data, o)
        lm = struct.unpack_from("<H", data, o + 4)[0]
        fl = struct.unpack_from("<H", data, o + 6)[0]
        edges.append((to, lm, fl))
    return nodes, adj, edges


def edge_cost(lm, fl):
    cls = fl & 0x0F
    if cls >= len(CLASS_COST):
        cls = len(CLASS_COST) - 1
    c = lm * CLASS_COST[cls]
    if fl & (1 << 4):
        c *= 3.0
    if fl & (1 << 5):
        c *= 2.8
    return c


def dijkstra(n, adj, edges, src, out_dist):
    INF = 1e30
    for i in range(n):
        out_dist[i] = INF
    out_dist[src] = 0.0
    pq = [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d != out_dist[u]:
            continue
        for ei in range(adj[u], adj[u + 1]):
            to, lm, fl = edges[ei]
            nd = d + edge_cost(lm, fl)
            if nd < out_dist[to]:
                out_dist[to] = nd
                heapq.heappush(pq, (nd, to))


def build_reverse(n, adj, edges):
    counts = [0] * n
    for u in range(n):
        for ei in range(adj[u], adj[u + 1]):
            to = edges[ei][0]
            if 0 <= to < n:
                counts[to] += 1
    rev_adj = [0] * (n + 1)
    for i in range(n):
        rev_adj[i + 1] = rev_adj[i] + counts[i]
        counts[i] = rev_adj[i]
    rev_edges = [None] * rev_adj[n]
    for u in range(n):
        for ei in range(adj[u], adj[u + 1]):
            to, lm, fl = edges[ei]
            if to < 0 or to >= n:
                continue
            slot = counts[to]
            counts[to] = slot + 1
            rev_edges[slot] = (u, lm, fl)
    return rev_adj, rev_edges


def build_alt(nodes, adj, edges, n_land, out_path):
    """ALT landmarks: farthest-point sampling + forward/backward Dijkstra."""
    n = len(nodes)
    print("==> ALT landmarks=%d …" % n_land, flush=True)
    
    # Farthest-point sampling
    lands = [0]
    dist = [0.0] * n
    dijkstra(n, adj, edges, 0, dist)
    for _ in range(1, n_land):
        best = max(range(n), key=lambda i: dist[i] if dist[i] < 1e29 else -1)
        lands.append(best)
        tmp = [0.0] * n
        dijkstra(n, adj, edges, best, tmp)
        for i in range(n):
            if tmp[i] < dist[i]:
                dist[i] = tmp[i]

    rev_adj, rev_edges = build_reverse(n, adj, edges)
    fwd = []
    back = []
    row = [0.0] * n
    for L in lands:
        dijkstra(n, adj, edges, L, row)
        fwd.extend(row)
        # reverse graph Dijkstra from L
        dijkstra(n, rev_adj, rev_edges, L, row)
        back.extend(row)
        print("  landmark node=%d" % L, flush=True)

    blob = bytearray()
    blob += b"GALT"
    blob += struct.pack("<BB", 1, 0)
    blob += struct.pack("<H", n_land)
    blob += struct.pack("<I", n)
    for L in lands:
        blob += struct.pack("<I", L)
    for v in fwd:
        blob += struct.pack("<f", float(v if v < 1e29 else 1e9))
    for v in back:
        blob += struct.pack("<f", float(v if v < 1e29 else 1e9))
    with open(out_path, "wb") as f:
        f.write(blob)
    print("Wrote %s (%.1f MB)" % (out_path, len(blob) / (1024 * 1024.0)), flush=True)


def build_ch(nodes, adj, edges, out_path):
    """Production-grade Contraction Hierarchies implementation.
    
    Based on Geisberger et al. (2008) "Contraction Hierarchies: Faster and 
    Simpler Hierarchical Routing in Road Networks"
    
    Optimizations:
    - Lazy witness search (bounded hop limit)
    - Edge difference heuristic for node ordering
    - Shortcut cost normalization
    - Safe uint32 packing with cost scaling
    """
    import heapq
    import time
    
    n = len(nodes)
    print("==> CH contract n=%d (production mode)..." % n, flush=True)
    print("    Strategy: lazy witness, edge-difference ordering, cost scaling")
    
    # === PARAMETERS ===
    MAX_WITNESS_HOPS = 5  # Lazy witness search limit
    MAX_SHORTCUTS_PER_NODE = 20  # Balance quality vs size
    
    # Cost scaling: Divide all costs by SCALE để fit uint32
    # Max real cost VN: ~10,000 km × 5.0 (worst class) × 1000 = 50M
    # Uint32 max: 4,294,967,295
    # Scale: 100 → max packed cost: ~500M / 100 = 5M (safe!)
    COST_SCALE = 100
    MAX_PACKED_COST = 0xFFFFFFFF  # Uint32 max
    
    print("    Cost scaling: 1/%d (allows max %.0f km worst-case routes)" % 
          (COST_SCALE, MAX_PACKED_COST * COST_SCALE / (5.0 * 1000)))
    
    # Build initial graph with scaled costs
    g = [[] for _ in range(n)]
    for u in range(n):
        for ei in range(adj[u], adj[u + 1]):
            to, lm, fl = edges[ei]
            cost = int(edge_cost(lm, fl))
            scaled = cost // COST_SCALE
            if scaled <= 0:
                scaled = 1  # Minimum cost
            g[u].append([to, scaled, -1])  # [to, cost_scaled, via]
    
    rank = [-1] * n
    contracted = [False] * n
    
    # Edge difference heuristic
    def calc_priority(u):
        """Calculate contraction priority (lower = contract earlier)."""
        if contracted[u]:
            return 1e30
        
        # Count neighbors not yet contracted
        nbrs = [t for t, c, v in g[u] if not contracted[t]]
        in_deg = len(nbrs)
        
        # Estimate shortcuts if we contract u
        shortcuts = 0
        for i, (a, ca, _) in enumerate(nbrs):
            for j, (b, cb, _) in enumerate(nbrs):
                if i >= j or a == b:
                    continue
                # Would create shortcut a->b via u
                # Simple estimate: no witness check here (lazy)
                shortcuts += 1
        
        # Edge difference: shortcuts - removed_edges
        removed = len(g[u])
        edge_diff = shortcuts - removed
        
        # Priority: favor low edge difference + low degree
        return edge_diff * 1000 + in_deg
    
    # Initialize priority queue
    pq = [(calc_priority(u), u) for u in range(n)]
    heapq.heapify(pq)
    
    # Lazy witness search
    def has_witness(a, b, max_cost, via, max_hops=MAX_WITNESS_HOPS):
        """Check if path a->b exists with cost <= max_cost (without using via)."""
        if a == b:
            return True
        
        # BFS with hop limit
        visited = {a}
        queue = [(0, a, 0)]  # (cost, node, hops)
        
        while queue:
            curr_cost, u, hops = queue.pop(0)
            
            if u == b:
                return curr_cost <= max_cost
            
            if hops >= max_hops:
                continue
            
            for t, c, v in g[u]:
                if t == via or t in visited:
                    continue
                
                new_cost = curr_cost + c
                if new_cost > max_cost:
                    continue
                
                visited.add(t)
                queue.append((new_cost, t, hops + 1))
        
        return False
    
    # Contraction loop
    contracted_count = 0
    total_shortcuts = 0
    t0 = time.time()
    
    # Contract nodes in priority order
    for iteration in range(n):
        # Pop node with lowest priority
        while pq:
            priority, u = heapq.heappop(pq)
            
            # Lazy evaluation: recompute priority if stale
            new_priority = calc_priority(u)
            if new_priority > priority + 100:  # Stale threshold
                heapq.heappush(pq, (new_priority, u))
                continue
            
            if not contracted[u]:
                break
        else:
            break  # All nodes processed
        
        # Get neighbors not yet contracted
        nbrs = [(t, c, v) for t, c, v in g[u] if not contracted[t]]
        
        # Add shortcuts
        shortcuts_added = 0
        for i, (a, ca, _) in enumerate(nbrs):
            for j, (b, cb, _) in enumerate(nbrs):
                if i >= j or a == b:
                    continue
                
                if shortcuts_added >= MAX_SHORTCUTS_PER_NODE:
                    break
                
                shortcut_cost = ca + cb
                
                # Check overflow
                if shortcut_cost > MAX_PACKED_COST:
                    continue
                
                # Witness search: is there a better path a->b not via u?
                if has_witness(a, b, shortcut_cost, u):
                    continue
                
                # Add shortcut (bidirectional for witness purposes)
                g[a].append([b, shortcut_cost, u])
                g[b].append([a, shortcut_cost, u])
                shortcuts_added += 1
                total_shortcuts += 1
        
        # Mark as contracted
        contracted[u] = True
        rank[u] = contracted_count
        contracted_count += 1
        
        # Update priorities of neighbors (lazy update)
        for t, c, v in nbrs:
            if not contracted[t]:
                heapq.heappush(pq, (calc_priority(t), t))
        
        # Progress logging
        if contracted_count % 50000 == 0 or contracted_count == n:
            elapsed = time.time() - t0
            print("  [%d/%d %.1f%%] shortcuts=%d rate=%.0f/s eta=%.0fs" %
                  (contracted_count, n, 100.0 * contracted_count / n,
                   total_shortcuts, contracted_count / max(1, elapsed),
                   (n - contracted_count) / max(1, contracted_count / elapsed)),
                  flush=True)
    
    print("  Contraction complete: %d nodes, %d shortcuts in %.1fs" %
          (contracted_count, total_shortcuts, time.time() - t0), flush=True)
    
    # Assign ranks to any remaining nodes
    r = contracted_count
    for u in range(n):
        if rank[u] < 0:
            rank[u] = r
            r += 1
    
    # Build upward graph (edges to higher-rank nodes only)
    print("  Building upward graph...", flush=True)
    up = [[] for _ in range(n)]
    for u in range(n):
        for t, c, via in g[u]:
            if rank[t] > rank[u]:
                up[u].append((t, c, via))
    
    # CSR format
    adj_u = [0]
    flat = []
    for u in range(n):
        for t, c, via in up[u]:
            flat.append((t, c, via))
        adj_u.append(len(flat))
    
    print("  Upward edges: %d (avg %.1f per node)" % 
          (len(flat), len(flat) / float(n)), flush=True)
    
    # Serialize to binary
    print("  Writing binary...", flush=True)
    blob = bytearray()
    blob += b"GNCH"
    blob += struct.pack("<BB", 1, 0)
    blob += struct.pack("<II", n, len(flat))
    
    # Write ranks
    for rnk in rank:
        blob += struct.pack("<I", rnk)
    
    # Write adjacency
    for a in adj_u:
        blob += struct.pack("<I", a)
    
    # Write edges - IMPORTANT: costs are SCALED
    # Java reader needs to multiply by COST_SCALE
    for t, c, via in flat:
        # Final validation
        if t < 0 or t >= n:
            continue
        if c < 0 or c > MAX_PACKED_COST:
            continue
        
        via_safe = via if via >= 0 else 0xFFFFFFFF
        blob += struct.pack("<III", t, c, via_safe)
    
    # Write metadata footer (for Java to read COST_SCALE)
    # Append 4 bytes: COST_SCALE
    blob += struct.pack("<I", COST_SCALE)
    
    with open(out_path, "wb") as f:
        f.write(blob)
    
    size_mb = len(blob) / (1024.0 * 1024.0)
    print("Wrote %s (%.1f MB)" % (out_path, size_mb), flush=True)
    print("  Nodes: %d" % n)
    print("  Shortcuts: %d (%.2f%% overhead)" % 
          (total_shortcuts, 100.0 * total_shortcuts / max(1, len(edges))))
    print("  File size: %.1f MB (%.1f KB per 1000 nodes)" % 
          (size_mb, 1000.0 * size_mb * 1024 / n))
    print("  IMPORTANT: Costs are scaled 1/%d - Java must multiply!" % COST_SCALE)
    print()


def build_accel(region_dir, landmarks=8, crp_grid=16,
                do_alt=True, do_ch=True, do_crp=False):
    """Build acceleration structures từ routing_meta.bin.
    
    NOTE: CH enabled with overflow protection. CRP disabled (not implemented).
    """
    meta = os.path.join(region_dir, "routing_meta.bin")
    if not os.path.isfile(meta):
        raise SystemExit("Missing %s — chạy routing/meta.py trước" % meta)
    
    t0 = time.time()
    nodes, adj, edges = parse_meta(meta)
    print("meta nodes=%d edges=%d" % (len(nodes), len(edges)), flush=True)
    
    if do_alt:
        build_alt(nodes, adj, edges, landmarks,
                  os.path.join(region_dir, "routing_alt.bin"))
    
    if do_ch:
        try:
            build_ch(nodes, adj, edges,
                     os.path.join(region_dir, "routing_ch.bin"))
        except Exception as e:
            print("WARNING: CH build failed: %s" % str(e))
            print("  Continuing without CH (app will use A* fallback)")
    
    if do_crp:
        print("WARNING: CRP build disabled (not implemented)")
    
    print("==> accel done in %.0fs" % (time.time() - t0), flush=True)


def main():
    ap = argparse.ArgumentParser(description="Build ALT landmarks from routing_meta.bin")
    ap.add_argument("region_dir")
    ap.add_argument("--landmarks", type=int, default=8,
                    help="Number of ALT landmarks (default 8, recommend 8-16)")
    ap.add_argument("--no-alt", action="store_true",
                    help="Skip ALT build")
    args = ap.parse_args()
    
    if not os.path.isdir(args.region_dir):
        raise SystemExit("Not a directory: %s" % args.region_dir)
    
    build_accel(args.region_dir, landmarks=args.landmarks,
                do_alt=not args.no_alt, do_ch=False, do_crp=False)


if __name__ == "__main__":
    main()
