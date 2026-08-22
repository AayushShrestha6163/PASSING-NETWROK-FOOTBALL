#!/usr/bin/env python3
"""
Passing Networks analysis server via stdin/stdout.
Data loaded ONCE at startup. Reads JSON lines from stdin, writes JSON lines to stdout.
Auto-started by Next.js - no separate server to manage.

Ports ALL calculations from the legacy passing-networks api_server.py.
"""
import sys
import json
import os
import math
import time
import traceback

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Redirect all prints to stderr so stdout stays clean for JSON
_real_stdout = sys.stdout
sys.stdout = sys.stderr

print("Loading passing-networks data...", flush=True)

import pandas as pd
import numpy as np
from collections import defaultdict

# ---------------------------------------------------------------------------
# PLAYER NICKNAMES
# ---------------------------------------------------------------------------
PLAYER_NICKNAMES = {
    "Carlos Henrique Casimiro": "Casemiro",
    "Cristiano Ronaldo dos Santos Aveiro": "Cristiano Ronaldo",
    "Daniel Carvajal Ramos": "Carvajal",
    "Francisco Rom\u00e1n Alarc\u00f3n Su\u00e1rez": "Isco",
    "Gareth Frank Bale": "Gareth Bale",
    "Jos\u00e9 Ignacio Fern\u00e1ndez Iglesias": "Nacho",
    "Keylor Navas Gamboa": "Keylor Navas",
    "Marcelo Vieira da Silva J\u00fanior": "Marcelo",
    "Marco Asensio Willemsen": "Asensio",
    "Sergio Ramos Garc\u00eda": "Sergio Ramos",
    "Roberto Firmino Barbosa de Oliveira": "Firmino",
    "Trent Alexander-Arnold": "Alexander-Arnold",
    "Virgil van Dijk": "Van Dijk",
    "Alisson Rams\u00e9s Becker": "Alisson",
    "F\u00e1bio Henrique Tavares": "Fabinho",
    "Jordan Brian Henderson": "Henderson",
    "James Philip Milner": "Milner",
    "Jo\u00ebl Andre Job Matip": "Matip",
    "Divock Okoth Origi": "Origi",
    "Bamidele Alli": "Dele Alli",
    "Christian Dannemann Eriksen": "Eriksen",
    "Fernando Llorente Torres": "Llorente",
    "Heung-Min Son": "Son",
    "Lucas Rodrigues Moura da Silva": "Lucas Moura",
}

# ---------------------------------------------------------------------------
# BUILDUP xT GRID (Karun Singh 12x8)
# ---------------------------------------------------------------------------
# Karun Singh's xT Grid (12x8) for buildup analysis — matches legacy exactly
BUILDUP_XT_GRID = [
    [0.006383, 0.007796, 0.008449, 0.009777, 0.011263, 0.012483, 0.014736, 0.017451, 0.021221, 0.027563, 0.034851, 0.037926],
    [0.007501, 0.008786, 0.009424, 0.010595, 0.012147, 0.013845, 0.016118, 0.018703, 0.024015, 0.029533, 0.040670, 0.046477],
    [0.008755, 0.010019, 0.010837, 0.012098, 0.014015, 0.016610, 0.019529, 0.023622, 0.031649, 0.043763, 0.062378, 0.083905],
    [0.009425, 0.010827, 0.011606, 0.013027, 0.015263, 0.017827, 0.021323, 0.026422, 0.036689, 0.053848, 0.088217, 0.257454],
    [0.009425, 0.010827, 0.011606, 0.013027, 0.015263, 0.017827, 0.021323, 0.026422, 0.036689, 0.053848, 0.088217, 0.257454],
    [0.008755, 0.010019, 0.010837, 0.012098, 0.014015, 0.016610, 0.019529, 0.023622, 0.031649, 0.043763, 0.062378, 0.083905],
    [0.007501, 0.008786, 0.009424, 0.010595, 0.012147, 0.013845, 0.016118, 0.018703, 0.024015, 0.029533, 0.040670, 0.046477],
    [0.006383, 0.007796, 0.008449, 0.009777, 0.011263, 0.012483, 0.014736, 0.017451, 0.021221, 0.027563, 0.034851, 0.037926],
]


def get_buildup_xt(x, y):
    """Get xT value for a position (StatsBomb coords: 120x80) — matches legacy."""
    if x is None or y is None or pd.isna(x) or pd.isna(y):
        return 0.0
    col = min(11, max(0, int(float(x) / 10)))
    row = min(7, max(0, int(float(y) / 10)))
    return BUILDUP_XT_GRID[row][col]


# ---------------------------------------------------------------------------
# DATA STORAGE

MATCH_DATA = {}


def load_data():
    """Load all match data from Excel files."""
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # Load Champions League finals
    cl_file = os.path.join(base_dir, "champions_league_finals_with_xt.xlsx")
    if os.path.exists(cl_file):
        xlsx = pd.ExcelFile(cl_file)
        for sheet in xlsx.sheet_names:
            df = pd.read_excel(xlsx, sheet_name=sheet)
            MATCH_DATA[sheet] = df
            print(f"  Loaded match {sheet}: {len(df)} events", flush=True)

    # Load additional matches (Euro 2024, World Cup 2022, etc.)
    additional_file = os.path.join(base_dir, "additional_matches_with_xt.xlsx")
    if os.path.exists(additional_file):
        try:
            xlsx = pd.ExcelFile(additional_file)
            for sheet in xlsx.sheet_names:
                if sheet == "Summary":
                    continue
                df = pd.read_excel(xlsx, sheet_name=sheet)
                MATCH_DATA[sheet] = df
                print(f"  Loaded match {sheet}: {len(df)} events", flush=True)
        except Exception as e:
            print(f"  Error loading additional matches: {e}", flush=True)

    if not MATCH_DATA:
        print("  WARNING: No data files found", flush=True)
        return 0

    print(f"  Total matches loaded: {len(MATCH_DATA)}", flush=True)
    return len(MATCH_DATA)


# ---------------------------------------------------------------------------
# NICKNAME HELPER

def get_nickname(full_name):
    """Get a short display name for a player."""
    if full_name in PLAYER_NICKNAMES:
        return PLAYER_NICKNAMES[full_name]
    if pd.isna(full_name):
        return "Unknown"
    parts = str(full_name).split()
    if len(parts) >= 3:
        return parts[-1]
    return str(full_name)


# ---------------------------------------------------------------------------
# BETWEENNESS CENTRALITY (Floyd-Warshall)

def calculate_betweenness_centrality(pass_matrix, all_players):
    """Floyd-Warshall based betweenness centrality."""
    n = len(all_players)
    if n < 3:
        return {p: 0.0 for p in all_players}

    player_idx = {p: i for i, p in enumerate(all_players)}

    INF = float("inf")
    # Distance matrix
    dist = [[INF] * n for _ in range(n)]
    # Next-hop matrix for path reconstruction
    nxt = [[None] * n for _ in range(n)]

    for i in range(n):
        dist[i][i] = 0

    for passer, recipients in pass_matrix.items():
        if passer not in player_idx:
            continue
        i = player_idx[passer]
        for recipient, count in recipients.items():
            if recipient not in player_idx:
                continue
            j = player_idx[recipient]
            if count > 0:
                d = 1.0 / count
                if d < dist[i][j]:
                    dist[i][j] = d
                    nxt[i][j] = j

    # Floyd-Warshall
    for k in range(n):
        for i in range(n):
            for j in range(n):
                if dist[i][k] + dist[k][j] < dist[i][j]:
                    dist[i][j] = dist[i][k] + dist[k][j]
                    nxt[i][j] = nxt[i][k]

    # Count shortest paths through each node
    betweenness = [0.0] * n

    for s in range(n):
        for t in range(n):
            if s == t:
                continue
            if dist[s][t] == INF:
                continue
            # Reconstruct path
            path = []
            current = s
            while current is not None and current != t:
                path.append(current)
                current = nxt[current][t]
            if current == t:
                path.append(t)
            else:
                continue
            # Count intermediaries
            for node in path[1:-1]:
                betweenness[node] += 1

    # Normalize by (n-1)*(n-2)
    norm = (n - 1) * (n - 2)
    result = {}
    for player in all_players:
        i = player_idx[player]
        result[player] = round(betweenness[i] / norm, 4) if norm > 0 else 0.0

    return result


# ---------------------------------------------------------------------------
# CLUSTERING COEFFICIENT

def calculate_clustering_coefficient(pass_matrix, all_players):
    """Calculate clustering coefficient for each player."""
    result = {}
    player_set = set(all_players)

    for player in all_players:
        # Get neighbors (outgoing + incoming)
        neighbors = set()
        if player in pass_matrix:
            for r in pass_matrix[player]:
                if pass_matrix[player][r] > 0:
                    neighbors.add(r)
        for passer in pass_matrix:
            if passer in player_set and player in pass_matrix[passer] and pass_matrix[passer][player] > 0:
                neighbors.add(passer)
        neighbors.discard(player)

        k = len(neighbors)
        if k < 2:
            result[player] = 0.0
            continue

        # Count edges between neighbors (either direction)
        neighbor_list = list(neighbors)
        neighbor_edges = 0
        for i_idx in range(len(neighbor_list)):
            for j_idx in range(i_idx + 1, len(neighbor_list)):
                n1 = neighbor_list[i_idx]
                n2 = neighbor_list[j_idx]
                has_edge = False
                if n1 in pass_matrix and n2 in pass_matrix[n1] and pass_matrix[n1][n2] > 0:
                    has_edge = True
                if n2 in pass_matrix and n1 in pass_matrix[n2] and pass_matrix[n2][n1] > 0:
                    has_edge = True
                if has_edge:
                    neighbor_edges += 1

        max_edges = k * (k - 1) / 2.0
        result[player] = round(neighbor_edges / max_edges, 4) if max_edges > 0 else 0.0

    return result


# ---------------------------------------------------------------------------
# EIGENVECTOR CENTRALITY (Power Iteration)

def calculate_eigenvector_centrality(pass_matrix, all_players, iterations=100):
    """Power iteration eigenvector centrality."""
    n = len(all_players)
    if n == 0:
        return {}

    player_idx = {p: i for i, p in enumerate(all_players)}
    adj = [[0.0] * n for _ in range(n)]
    for passer, recipients in pass_matrix.items():
        if passer not in player_idx:
            continue
        i = player_idx[passer]
        for recipient, count in recipients.items():
            if recipient not in player_idx:
                continue
            j = player_idx[recipient]
            adj[i][j] += count
            adj[j][i] += count

    # Initialize centrality = 1/n
    centrality = [1.0 / n] * n

    for _ in range(iterations):
        new_centrality = [0.0] * n
        for i in range(n):
            for j in range(n):
                new_centrality[i] += adj[i][j] * centrality[j]
        # Normalize by L2 norm
        norm = math.sqrt(sum(c * c for c in new_centrality))
        if norm > 0:
            new_centrality = [c / norm for c in new_centrality]
        centrality = new_centrality

    result = {}
    for player in all_players:
        i = player_idx[player]
        result[player] = round(centrality[i], 4)

    return result


# ---------------------------------------------------------------------------
# PASS SEQUENCES

def calculate_pass_sequences(df, team_name):
    """Track consecutive successful passes — matches legacy exactly."""
    team_events = df[df["team_name"] == team_name].sort_values(
        ["period", "minute", "second"]
    )

    sequences = []
    current_seq = 0

    for _, event in team_events.iterrows():
        event_type = event.get("event_type", "")

        if event_type == "Pass":
            if pd.isna(event.get("pass_outcome_name")):
                # Successful pass
                current_seq += 1
            else:
                # Failed pass ends sequence
                if current_seq > 0:
                    sequences.append(current_seq)
                current_seq = 0
        elif event_type in ["Ball Receipt*", "Carry"]:
            # Continue sequence (legacy: pass)
            pass
        elif event_type in [
            "Dispossessed",
            "Miscontrol",
            "Shot",
            "Clearance",
        ]:
            if current_seq > 0:
                sequences.append(current_seq)
            current_seq = 0

    # Don't forget the last sequence
    if current_seq > 0:
        sequences.append(current_seq)

    if not sequences:
        return {
            "avg_length": 0,
            "max_length": 0,
            "total_sequences": 0,
            "distribution": {},
        }

    distribution = defaultdict(int)
    for s in sequences:
        if s <= 3:
            distribution["1-3"] += 1
        elif s <= 6:
            distribution["4-6"] += 1
        elif s <= 10:
            distribution["7-10"] += 1
        else:
            distribution["11+"] += 1

    return {
        "avg_length": round(sum(sequences) / len(sequences), 2),
        "max_length": max(sequences),
        "total_sequences": len(sequences),
        "distribution": dict(distribution),
    }


# ---------------------------------------------------------------------------
# PPDA

def calculate_ppda(df, team_name):
    """
    PPDA = opponent_passes_in_their_half(x<60) /
           team_defensive_actions_in_opp_half(x>60).
    """
    # Get opponent team name — legacy filters NaN
    teams = df["team_name"].unique()
    opponent = [t for t in teams if t != team_name and pd.notna(t)]

    if not opponent:
        return {"ppda": 0, "opponent_passes": 0, "defensive_actions": 0}
    opp_team = opponent[0]

    # Opponent passes in their own half (x < 60)
    opp_passes = df[
        (df["team_name"] == opp_team)
        & (df["event_type"] == "Pass")
        & (df["location_0"] < 60)
    ]

    # Team defensive actions in opponent's half (x > 60).
    # Canonical PPDA (Colin Trainor, StatsBomb 2014; FBref; Wyscout; Opta) counts
    # Tackle + Interception + Foul Committed (+ Block). 'Pressure' is INTENTIONALLY
    # excluded — StatsBomb fires a Pressure event whenever a defender comes within
    # ~5 m of an opponent on the ball, regardless of whether anything happens.
    # Measured across the 31 matches in this dataset, a team logs roughly 90-190
    # Pressures vs only ~40-55 real defensive actions, so including Pressure
    # inflates the denominator about 3x (up to ~6x) and pushes almost every team
    # into a falsely low, "elite" PPDA.
    defensive_events = ["Tackle", "Interception", "Foul Committed", "Block"]
    team_def = df[
        (df["team_name"] == team_name)
        & (df["event_type"].isin(defensive_events))
        & (df["location_0"] > 60)
    ]

    opp_count = len(opp_passes)
    def_count = len(team_def)

    ppda_val = opp_count / max(def_count, 1)

    if ppda_val < 4:
        interpretation = "Elite pressing"
    elif ppda_val < 6:
        interpretation = "Very high pressing"
    elif ppda_val < 8:
        interpretation = "High pressing"
    elif ppda_val < 12:
        interpretation = "Moderate pressing"
    else:
        interpretation = "Low pressing"

    return {
        "ppda": round(ppda_val, 2),
        "opponent_passes": opp_count,
        "defensive_actions": def_count,
        "interpretation": interpretation,
    }


# ---------------------------------------------------------------------------
# PASS DIRECTIONS
# ---------------------------------------------------------------------------
def calculate_pass_directions(df, team_name):
    """
    8 directions — matches legacy: only successful passes, returns counts/percentages/avg_distance.
    """
    team_passes = df[
        (df["team_name"] == team_name)
        & (df["event_type"] == "Pass")
        & (df["pass_outcome_name"].isna())
    ]

    directions = {
        "forward": 0,
        "forward_right": 0,
        "right": 0,
        "back_right": 0,
        "back": 0,
        "back_left": 0,
        "left": 0,
        "forward_left": 0,
    }

    total_distance = 0
    pass_count = 0

    for _, row in team_passes.iterrows():
        if pd.isna(row.get("location_0")) or pd.isna(row.get("pass_end_location_0")):
            continue

        dx = row["pass_end_location_0"] - row["location_0"]
        dy = row["pass_end_location_1"] - row["location_1"]

        angle = math.degrees(math.atan2(dy, dx))
        angle = (angle + 360) % 360

        if angle < 22.5 or angle >= 337.5:
            directions["forward"] += 1
        elif angle < 67.5:
            directions["forward_right"] += 1
        elif angle < 112.5:
            directions["right"] += 1
        elif angle < 157.5:
            directions["back_right"] += 1
        elif angle < 202.5:
            directions["back"] += 1
        elif angle < 247.5:
            directions["back_left"] += 1
        elif angle < 292.5:
            directions["left"] += 1
        else:
            directions["forward_left"] += 1

        distance = math.sqrt(dx * dx + dy * dy)
        total_distance += distance
        pass_count += 1

    total = sum(directions.values())
    if total > 0:
        directions_pct = {k: round(v / total * 100, 1) for k, v in directions.items()}
    else:
        directions_pct = {k: 0 for k in directions}

    return {
        "counts": directions,
        "percentages": directions_pct,
        "avg_distance": round(total_distance / max(pass_count, 1), 2),
        "total_passes": total,
    }


# ---------------------------------------------------------------------------
# FIELD TILT
# ---------------------------------------------------------------------------
def calculate_field_tilt(df, team_name):
    """Comparative field tilt — the team's SHARE of all final-third (x >= 80)
    successful passes between the two teams in this match.

    field_tilt = team_final_third_passes / (team_final_third + opp_final_third) * 100

    Range 0-100. The two teams' field-tilt values always sum to 100 because
    a pass in the final third belongs to exactly one team. This matches the
    industry-standard definition (Twelve.football, FBref, StatsBomb articles)
    used by professional analysts. The team-internal "% of own passes in
    opponent's half" version is mathematically simpler but doesn't COMPARE
    territorial dominance between the two teams the way analysts mean when
    they say "field tilt", so we use the comparative version here.
    """
    teams = df["team_name"].unique()
    opponent = [t for t in teams if t != team_name and pd.notna(t)]
    if not opponent:
        return {"field_tilt": 50, "team_final_third_passes": 0, "opp_final_third_passes": 0, "total_final_third_passes": 0}
    opp_team = opponent[0]

    team_final_third = df[
        (df["team_name"] == team_name)
        & (df["event_type"] == "Pass")
        & (df["pass_outcome_name"].isna())
        & (df["location_0"] >= 80)
    ]
    opp_final_third = df[
        (df["team_name"] == opp_team)
        & (df["event_type"] == "Pass")
        & (df["pass_outcome_name"].isna())
        & (df["location_0"] >= 80)
    ]

    team_count = len(team_final_third)
    opp_count = len(opp_final_third)
    total = team_count + opp_count
    if total == 0:
        return {"field_tilt": 50, "team_final_third_passes": 0, "opp_final_third_passes": 0, "total_final_third_passes": 0}

    return {
        "field_tilt": round(team_count / total * 100, 1),
        "team_final_third_passes": team_count,
        "opp_final_third_passes": opp_count,
        "total_final_third_passes": total,
        # Back-compat aliases so any existing UI that read own_half/opponent_half
        # still gets sensible values — own_half = opponent's share, etc.
        "own_half": opp_count,
        "opponent_half": team_count,
        "total": total,
    }


# ---------------------------------------------------------------------------
# TEAM SHAPE
# ---------------------------------------------------------------------------
def calculate_team_shape(df, team_name):
    """Team shape metrics — matches legacy: successful passes only, returns avg_width/avg_depth/avg_player_distance/compactness."""
    team_passes = df[
        (df["team_name"] == team_name)
        & (df["event_type"] == "Pass")
        & (df["pass_outcome_name"].isna())
    ]

    if len(team_passes) == 0:
        return {"avg_width": 0, "avg_depth": 0, "compactness": 0}

    player_positions = team_passes.groupby("player_name").agg({
        "location_0": "mean",
        "location_1": "mean",
    }).dropna()

    if len(player_positions) < 2:
        return {"avg_width": 0, "avg_depth": 0, "compactness": 0}

    width = player_positions["location_1"].max() - player_positions["location_1"].min()
    depth = player_positions["location_0"].max() - player_positions["location_0"].min()

    distances = []
    positions = player_positions.values.tolist()
    for i, p1 in enumerate(positions):
        for p2 in positions[i + 1:]:
            dist = math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)
            distances.append(dist)

    avg_distance = sum(distances) / len(distances) if distances else 0
    compactness = round(100 / max(avg_distance, 1), 2)

    return {
        "avg_width": round(width, 1),
        "avg_depth": round(depth, 1),
        "avg_player_distance": round(avg_distance, 1),
        "compactness": compactness,
    }


# ---------------------------------------------------------------------------
# NETWORK METRICS (core)
# ---------------------------------------------------------------------------
def calculate_network_metrics(passes_df, team_name):
    """Calculate network analysis metrics for a team — matches legacy api_server.py"""
    team_passes = passes_df[
        (passes_df["team_name"] == team_name)
        & (passes_df["event_type"] == "Pass")
        & (passes_df["pass_outcome_name"].isna())
    ].copy()

    if len(team_passes) == 0:
        return None

    players_set = set(team_passes["player_name"].dropna().unique())
    recipients_set = set(team_passes["pass_recipient_name"].dropna().unique())
    all_players = list(players_set.union(recipients_set))

    pass_matrix = defaultdict(lambda: defaultdict(int))
    pass_locations = defaultdict(list)

    for _, row in team_passes.iterrows():
        passer = row["player_name"]
        recipient = row["pass_recipient_name"]
        if pd.notna(passer) and pd.notna(recipient):
            pass_matrix[passer][recipient] += 1
            if pd.notna(row["location_0"]) and pd.notna(row["location_1"]):
                pass_locations[passer].append((row["location_0"], row["location_1"]))

    # Calculate xT per player if available
    has_xt = "xt_added" in team_passes.columns and not team_passes["xt_added"].isna().all()
    player_xt = {}
    if has_xt:
        xt_by_player = team_passes.groupby("player_name")["xt_added"].sum()
        player_xt = {name: round(xt, 4) for name, xt in xt_by_player.items()}

    # Track when each player was active (both passer and recipient)
    player_minutes = {}
    if "minute" in team_passes.columns:
        for player in all_players:
            if pd.isna(player):
                continue
            player_passes = team_passes[
                (team_passes["player_name"] == player)
                | (team_passes["pass_recipient_name"] == player)
            ]
            if len(player_passes) > 0:
                first_min = int(player_passes["minute"].min()) if pd.notna(player_passes["minute"].min()) else 0
                last_min = int(player_passes["minute"].max()) if pd.notna(player_passes["minute"].max()) else 90
                player_minutes[player] = {"first_minute": first_min, "last_minute": last_min}

    player_stats = {}
    total_passes = sum(sum(p.values()) for p in pass_matrix.values())

    for player in all_players:
        if pd.isna(player):
            continue

        passes_made = sum(pass_matrix[player].values())
        passes_received = sum(pass_matrix[p][player] for p in pass_matrix)

        connections_out = len([r for r in pass_matrix[player] if pass_matrix[player][r] > 0])
        connections_in = len([p for p in pass_matrix if pass_matrix[p][player] > 0])
        degree_centrality = (connections_out + connections_in) / (2 * max(len(all_players) - 1, 1))

        locs = pass_locations.get(player, [])
        if locs:
            avg_x = np.mean([l[0] for l in locs])
            avg_y = np.mean([l[1] for l in locs])
        else:
            avg_x, avg_y = 60, 40

        minutes_info = player_minutes.get(player, {"first_minute": 0, "last_minute": 90})

        player_stats[player] = {
            "name": player,
            "nickname": get_nickname(player),
            "passes_made": passes_made,
            "passes_received": passes_received,
            "total_involvement": passes_made + passes_received,
            "degree_centrality": round(degree_centrality, 3),
            "avg_x": round(float(avg_x), 1),
            "avg_y": round(float(avg_y), 1),
            "connections_out": connections_out,
            "connections_in": connections_in,
            "xt_generated": player_xt.get(player, 0) if has_xt else None,
            "first_minute": minutes_info["first_minute"],
            "last_minute": minutes_info["last_minute"],
        }

    edges = []
    for passer in pass_matrix:
        for recipient in pass_matrix[passer]:
            count = pass_matrix[passer][recipient]
            if count > 0 and passer in player_stats and recipient in player_stats:
                edges.append({
                    "source": passer,
                    "source_nickname": get_nickname(passer),
                    "target": recipient,
                    "target_nickname": get_nickname(recipient),
                    "weight": count,
                    "source_x": player_stats[passer]["avg_x"],
                    "source_y": player_stats[passer]["avg_y"],
                    "target_x": player_stats[recipient]["avg_x"],
                    "target_y": player_stats[recipient]["avg_y"],
                })

    # Advanced centrality
    betweenness = calculate_betweenness_centrality(pass_matrix, all_players)
    clustering_vals = calculate_clustering_coefficient(pass_matrix, all_players)
    eigenvector = calculate_eigenvector_centrality(pass_matrix, all_players)

    for player in player_stats:
        player_stats[player]["betweenness_centrality"] = betweenness.get(player, 0)
        player_stats[player]["clustering_coefficient"] = clustering_vals.get(player, 0)
        player_stats[player]["eigenvector_centrality"] = eigenvector.get(player, 0)

    num_players = len(player_stats)
    num_edges = len(edges)
    max_edges = num_players * (num_players - 1)
    network_density = num_edges / max(max_edges, 1)

    hub = max(player_stats.values(), key=lambda x: x["total_involvement"]) if player_stats else None

    return {
        "team": team_name,
        "players": list(player_stats.values()),
        "edges": edges,
        "metrics": {
            "total_passes": total_passes,
            "num_players": num_players,
            "num_connections": num_edges,
            "network_density": round(network_density, 3),
            "hub_player": hub["name"] if hub else None,
            "hub_centrality": hub["degree_centrality"] if hub else 0,
            "hub_involvement": hub["total_involvement"] if hub else 0,
        },
        "pass_matrix": {k: dict(v) for k, v in pass_matrix.items()},
    }


# ---------------------------------------------------------------------------
# WEAKEST LINK
# ---------------------------------------------------------------------------
def calculate_weakest_link(df, team_name, network_data):
    """
    Matches legacy api_server.py calculate_weakest_link exactly.
    3-component scoring with position-specific weights.
    Position detection by avg_x only.
    """
    if not network_data or "players" not in network_data:
        return None

    players = network_data["players"]
    if len(players) < 3:
        return None

    # Get all passes for pressure analysis
    team_passes = df[
        (df["team_name"] == team_name) & (df["event_type"] == "Pass")
    ]

    # Max values for normalization — matches legacy
    max_eigen = max((p.get("eigenvector_centrality", 0) for p in players), default=1) or 1
    max_cluster = max((p.get("clustering_coefficient", 0) for p in players), default=1) or 1
    max_between = max((p.get("betweenness_centrality", 0) for p in players), default=1) or 1
    max_involvement = max((p.get("total_involvement", 0) for p in players), default=1) or 1

    weakness_scores = []

    for player in players:
        player_name = player.get("name")
        if not player_name or pd.isna(player_name):
            continue

        # Position detection by avg_x only — matches legacy
        avg_x = player.get("avg_x", 60)
        avg_y = player.get("avg_y", 40)

        if avg_x < 25:
            position = "Goalkeeper"
            position_weights = {"composite": 0.20, "pressure": 0.70, "xt_bottleneck": 0.10}
            position_explanation = "Goalkeepers are expected to clear danger, not progress attacks. Pressure handling is critical."
        elif avg_x < 50:
            position = "Defender"
            position_weights = {"composite": 0.35, "pressure": 0.40, "xt_bottleneck": 0.25}
            position_explanation = "Defenders should balance safety with ball progression. Handling pressure is crucial to prevent goals."
        elif avg_x < 80:
            position = "Midfielder"
            position_weights = {"composite": 0.30, "pressure": 0.30, "xt_bottleneck": 0.40}
            position_explanation = "Midfielders are the engine room - they must progress the ball and handle pressure while staying connected."
        else:
            position = "Forward"
            position_weights = {"composite": 0.50, "pressure": 0.35, "xt_bottleneck": 0.15}
            position_explanation = "Forwards are attack endpoints - they shoot rather than pass forward. Low xT generation is expected."

        # Skip goalkeepers with very low involvement — matches legacy
        if position == "Goalkeeper" and player.get("total_involvement", 0) < 10:
            continue

        # 1. Composite vulnerability — legacy weights: eigen 0.4, cluster 0.35, between 0.25
        eigen = player.get("eigenvector_centrality", 0)
        cluster = player.get("clustering_coefficient", 0)
        between = player.get("betweenness_centrality", 0)

        eigen_weakness = 1 - (eigen / max_eigen) if max_eigen > 0 else 0
        cluster_weakness = 1 - (cluster / max_cluster) if max_cluster > 0 else 0
        between_weakness = 1 - (between / max_between) if max_between > 0 else 0

        composite_vulnerability = (eigen_weakness * 0.4 + cluster_weakness * 0.35 + between_weakness * 0.25)

        # 2. Pressure vulnerability — matches legacy exactly
        player_passes = team_passes[team_passes["player_name"] == player_name]

        if len(player_passes) >= 5:
            normal_passes = player_passes[
                player_passes["under_pressure"].isna() | (player_passes["under_pressure"] == False)
            ]
            normal_success = normal_passes[normal_passes["pass_outcome_name"].isna()]
            normal_accuracy = len(normal_success) / len(normal_passes) * 100 if len(normal_passes) > 0 else 80

            pressure_passes = player_passes[player_passes["under_pressure"] == True]
            pressure_success = pressure_passes[pressure_passes["pass_outcome_name"].isna()]
            pressure_accuracy = len(pressure_success) / len(pressure_passes) * 100 if len(pressure_passes) > 0 else normal_accuracy

            accuracy_drop = max(0, normal_accuracy - pressure_accuracy)
            pressure_vulnerability = min(accuracy_drop / 40, 1)

            if len(pressure_passes) >= 3 and pressure_accuracy < 50:
                pressure_vulnerability = min(pressure_vulnerability + 0.3, 1)
        else:
            pressure_vulnerability = 0.5
            normal_accuracy = 0
            pressure_accuracy = 0
            accuracy_drop = 0
            normal_passes = player_passes
            pressure_passes = pd.DataFrame()

        # 3. xT bottleneck — matches legacy exactly
        xt_generated = player.get("xt_generated", 0) or 0

        if "xt_added" in df.columns:
            passes_to_player = team_passes[
                (team_passes["pass_recipient_name"] == player_name)
                & (team_passes["pass_outcome_name"].isna())
            ]
            xt_received = passes_to_player["xt_added"].sum() if len(passes_to_player) > 0 else 0
        else:
            xt_received = 0

        if xt_received > 0.1:
            xt_efficiency = xt_generated / xt_received
            xt_bottleneck = max(0, min(1, 1 - xt_efficiency))
        elif xt_generated < 0:
            xt_bottleneck = 0.8
        else:
            xt_bottleneck = 0.3

        # Forward special handling — matches legacy
        if position == "Forward" and xt_generated < 0:
            player_shots = df[(df["player_name"] == player_name) & (df["event_type"] == "Shot")]
            if len(player_shots) > 0:
                xt_bottleneck *= 0.5

        # Final weighted score
        total_weakness = (
            composite_vulnerability * position_weights["composite"]
            + pressure_vulnerability * position_weights["pressure"]
            + xt_bottleneck * position_weights["xt_bottleneck"]
        )

        # Involvement ratio penalty — matches legacy
        involvement = player.get("total_involvement", 0)
        involvement_ratio = involvement / max_involvement if max_involvement > 0 else 0
        if involvement_ratio < 0.15:
            total_weakness *= 0.5

        # Reasons — matches legacy
        reasons = []
        if composite_vulnerability > 0.6:
            reasons.append(f"Low network integration (eigenvector: {eigen:.3f}, clustering: {cluster:.3f})")
        if pressure_vulnerability > 0.5:
            if len(player_passes) >= 5 and len(pressure_passes) >= 3:
                reasons.append(f"Struggles under pressure ({pressure_accuracy:.0f}% accuracy, {accuracy_drop:.0f}pp drop)")
            else:
                reasons.append("Limited pressure resistance data")
        if xt_bottleneck > 0.5 and position_weights["xt_bottleneck"] >= 0.25:
            if xt_generated < 0:
                reasons.append(f"Negative threat contribution (xT: {xt_generated:.3f})")
            elif xt_received > 0.1:
                reasons.append(f"xT bottleneck (received: {xt_received:.3f}, generated: {xt_generated:.3f})")

        total_passes_made = len(player_passes)
        successful_passes = len(player_passes[player_passes["pass_outcome_name"].isna()])
        overall_accuracy = (successful_passes / total_passes_made * 100) if total_passes_made > 0 else 0

        if len(player_passes) >= 5:
            normal_pass_count = len(normal_passes)
            pressure_pass_count = len(pressure_passes)
        else:
            normal_pass_count = len(player_passes)
            pressure_pass_count = 0
            normal_accuracy = overall_accuracy
            pressure_accuracy = overall_accuracy
            accuracy_drop = 0

        player_shots_df = df[(df["player_name"] == player_name) & (df["event_type"] == "Shot")]
        shots_count = len(player_shots_df)

        weakness_scores.append({
            "player": player_name,
            "nickname": get_nickname(player_name),
            "weakness_score": round(total_weakness, 4),
            "composite_vulnerability": round(composite_vulnerability, 4),
            "pressure_vulnerability": round(pressure_vulnerability, 4),
            "xt_bottleneck": round(min(xt_bottleneck, 1), 4),
            "reasons": reasons,
            "position_info": {
                "position": position,
                "avg_x": round(avg_x, 1),
                "avg_y": round(avg_y, 1),
                "explanation": position_explanation,
                "weights": {
                    "composite": int(position_weights["composite"] * 100),
                    "pressure": int(position_weights["pressure"] * 100),
                    "xt_bottleneck": int(position_weights["xt_bottleneck"] * 100),
                },
            },
            "metrics": {
                "eigenvector_centrality": round(eigen, 4),
                "clustering_coefficient": round(cluster, 4),
                "betweenness_centrality": round(between, 4),
                "xt_generated": round(xt_generated, 4),
                "xt_received": round(float(xt_received) if not pd.isna(xt_received) else 0, 4),
                "total_involvement": involvement,
            },
            "detailed_stats": {
                "passes_made": total_passes_made,
                "passes_successful": successful_passes,
                "overall_accuracy": round(overall_accuracy, 1),
                "normal_passes": normal_pass_count,
                "normal_accuracy": round(normal_accuracy, 1),
                "pressure_passes": pressure_pass_count,
                "pressure_accuracy": round(pressure_accuracy, 1),
                "accuracy_drop": round(accuracy_drop, 1),
                "connections_in": player.get("connections_in", 0),
                "connections_out": player.get("connections_out", 0),
                "passes_received": player.get("passes_received", 0),
                "shots": shots_count,
            },
            "position": {
                "x": player.get("avg_x", 60),
                "y": player.get("avg_y", 40),
            },
        })

    if not weakness_scores:
        return None

    weakness_scores.sort(key=lambda x: x["weakness_score"], reverse=True)
    weakest = weakness_scores[0]

    explanation_parts = []
    if weakest["composite_vulnerability"] > 0.5:
        explanation_parts.append("isolated from the core passing structure")
    if weakest["pressure_vulnerability"] > 0.5:
        explanation_parts.append("vulnerable when opponents press")
    if weakest["xt_bottleneck"] > 0.5:
        explanation_parts.append("fails to progress attacks effectively")

    if explanation_parts:
        explanation = f"{weakest['nickname']} is identified as the weakest link because they are " + ", and ".join(explanation_parts) + "."
    else:
        explanation = f"{weakest['nickname']} shows the highest composite vulnerability score in the network."

    return {
        "weakest_link": weakest,
        "all_scores": weakness_scores[:5],
        "explanation": explanation,
        "methodology": {
            "composite_weight": 0.40,
            "pressure_weight": 0.30,
            "xt_weight": 0.30,
            "description": "Combines network position vulnerability, pressure resistance, and threat generation efficiency",
        },
    }


# ---------------------------------------------------------------------------
# PROGRESSIVE PASSES
# ---------------------------------------------------------------------------
def get_progressive_passes(df, team_name):
    """Passes where end_x - start_x >= 10 — matches legacy: only isna() passes."""
    passes = df[
        (df["team_name"] == team_name)
        & (df["event_type"] == "Pass")
        & (df["pass_end_location_0"].notna())
        & (df["location_0"].notna())
        & (df["pass_outcome_name"].isna())
    ]

    progressive = passes[
        (passes["pass_end_location_0"] - passes["location_0"]) >= 10
    ]

    result = []
    for _, p in progressive.iterrows():
        result.append(
            {
                "player": str(p["player_name"]),
                "nickname": get_nickname(p["player_name"]),
                "recipient": str(p.get("pass_recipient_name", "")),
                "recipient_nickname": get_nickname(p.get("pass_recipient_name", "")),
                "start_x": float(p["location_0"]) if not pd.isna(p["location_0"]) else 0,
                "start_y": float(p["location_1"]) if not pd.isna(p["location_1"]) else 0,
                "end_x": float(p["pass_end_location_0"]) if not pd.isna(p["pass_end_location_0"]) else 0,
                "end_y": float(p["pass_end_location_1"]) if not pd.isna(p["pass_end_location_1"]) else 0,
                "distance": round(
                    float(p["pass_end_location_0"] - p["location_0"]), 1
                ),
                "minute": int(p["minute"]) if not pd.isna(p.get("minute", None)) else 0,
                "xt_added": round(float(p.get("xt_added", 0)), 4) if not pd.isna(p.get("xt_added", 0)) else 0,
            }
        )

    return result


# ---------------------------------------------------------------------------
# ADVANCED INSIGHTS
# ---------------------------------------------------------------------------
def calculate_advanced_insights(df, team_name):
    """Calculate advanced analytical insights — matches legacy api_server.py"""
    insights = {
        "vulnerabilities": [],
        "strengths": [],
        "key_moments": [],
        "progressive_stats": {},
        "pressure_stats": {},
        "territorial": {},
        "xt_stats": {},
        "narrative": {},
        "pass_sequences": {},
        "ppda": {},
        "pass_directions": {},
        "field_tilt": {},
        "team_shape": {},
        "advanced_network": {},
    }

    team_df = df[df["team_name"] == team_name]
    team_passes = team_df[team_df["event_type"] == "Pass"].copy()
    successful_passes = team_passes[team_passes["pass_outcome_name"].isna()]
    failed_passes = team_passes[team_passes["pass_outcome_name"].notna()]

    if len(team_passes) == 0:
        return insights

    # === PERIOD-AWARE SCALING ===
    min_minute = df["minute"].min() if "minute" in df.columns else 0
    max_minute = df["minute"].max() if "minute" in df.columns else 90
    period_duration = max(max_minute - min_minute, 1)
    scale_factor = min(period_duration / 90, 1.0)
    xt_low_threshold = 0.8 * scale_factor
    xt_high_threshold = 1.5 * scale_factor
    min_pressure_situations = max(5, int(10 * scale_factor))

    total_passes = len(team_passes)
    pass_accuracy = len(successful_passes) / total_passes * 100 if total_passes > 0 else 0

    # === xT ANALYSIS ===
    has_xt_data = "xt_added" in successful_passes.columns and not successful_passes["xt_added"].isna().all()

    if has_xt_data:
        total_xt = successful_passes["xt_added"].sum()
        avg_xt_per_pass = successful_passes["xt_added"].mean()
        positive_xt_passes = successful_passes[successful_passes["xt_added"] > 0]
        negative_xt_passes = successful_passes[successful_passes["xt_added"] < 0]

        player_xt = successful_passes.groupby("player_name")["xt_added"].sum().sort_values(ascending=False)
        top_xt_players = [(get_nickname(name), round(xt, 4)) for name, xt in player_xt.head(5).items()]

        xt_by_start_zone = {}
        for _, row in successful_passes.iterrows():
            if pd.notna(row.get("location_0")):
                if row["location_0"] < 40:
                    zone = "defensive"
                elif row["location_0"] < 80:
                    zone = "middle"
                else:
                    zone = "attacking"
                xt_by_start_zone[zone] = xt_by_start_zone.get(zone, 0) + (row.get("xt_added", 0) or 0)

        insights["xt_stats"] = {
            "total_xt": round(float(total_xt), 4),
            "avg_xt_per_pass": round(float(avg_xt_per_pass), 6),
            "positive_xt_passes": len(positive_xt_passes),
            "negative_xt_passes": len(negative_xt_passes),
            "top_xt_players": top_xt_players,
            "xt_by_zone": {k: round(v, 4) for k, v in xt_by_start_zone.items()},
            "has_data": True,
        }

        if total_xt > xt_high_threshold:
            insights["strengths"].append({
                "type": "high_xt_generation",
                "value": round(float(total_xt), 3),
                "message": f"Generated {round(float(total_xt), 3)} total xT from passing, indicating effective threat creation",
            })

        if len(positive_xt_passes) / len(successful_passes) > 0.4:
            threat_ratio = len(positive_xt_passes) / len(successful_passes) * 100
            insights["strengths"].append({
                "type": "threat_positive_ratio",
                "value": round(threat_ratio, 1),
                "message": f"{round(threat_ratio, 1)}% of passes increased threat - a sign of progressive, dangerous passing",
            })

        if total_xt < xt_low_threshold:
            severity_threshold = 0.5 * scale_factor
            insights["vulnerabilities"].append({
                "type": "low_xt_generation",
                "severity": "high" if total_xt < severity_threshold else "medium",
                "value": round(float(total_xt), 3),
                "message": f"Only {round(float(total_xt), 3)} total xT generated - passing lacks threat despite possession",
            })

        if len(player_xt) > 0:
            top_player_xt = player_xt.iloc[0]
            top_player_share = top_player_xt / total_xt * 100 if total_xt > 0 else 0
            if top_player_share > 35:
                insights["vulnerabilities"].append({
                    "type": "xt_concentration",
                    "severity": "medium",
                    "player": get_nickname(player_xt.index[0]),
                    "value": round(top_player_share, 1),
                    "message": f"{get_nickname(player_xt.index[0])} accounts for {round(top_player_share, 1)}% of team's threat generation",
                })
    else:
        insights["xt_stats"] = {"has_data": False}

    # === PROGRESSIVE PASSES ===
    progressive_passes = []
    for _, row in successful_passes.iterrows():
        if pd.notna(row.get("location_0")) and pd.notna(row.get("pass_end_location_0")):
            start_x = row["location_0"]
            end_x = row["pass_end_location_0"]
            if end_x - start_x >= 10:
                progressive_passes.append(row)

    progressive_count = len(progressive_passes)
    progressive_pct = progressive_count / len(successful_passes) * 100 if len(successful_passes) > 0 else 0

    insights["progressive_stats"] = {
        "count": progressive_count,
        "percentage": round(progressive_pct, 1),
        "total_successful": len(successful_passes),
    }

    # === PASSING STATS ===
    insights["passing_stats"] = {
        "total_attempted": total_passes,
        "total_successful": len(successful_passes),
        "total_failed": len(failed_passes),
        "accuracy": round(pass_accuracy, 1),
        "per_minute": round(total_passes / max(period_duration, 1), 2),
    }

    # === PASSES UNDER PRESSURE ===
    under_pressure = team_passes[team_passes["under_pressure"] == 1.0]
    pressure_successful = under_pressure[under_pressure["pass_outcome_name"].isna()]
    pressure_accuracy = len(pressure_successful) / len(under_pressure) * 100 if len(under_pressure) > 0 else 0

    insights["pressure_stats"] = {
        "passes_under_pressure": len(under_pressure),
        "pressure_accuracy": round(pressure_accuracy, 1),
        "normal_accuracy": round(pass_accuracy, 1),
        "pressure_resistance": round(pressure_accuracy - pass_accuracy, 1) if pass_accuracy > 0 else 0,
    }

    # === TERRITORIAL ANALYSIS ===
    def_third = successful_passes[successful_passes["location_0"] < 40]
    mid_third = successful_passes[(successful_passes["location_0"] >= 40) & (successful_passes["location_0"] < 80)]
    att_third = successful_passes[successful_passes["location_0"] >= 80]

    final_third_entries = successful_passes[
        (successful_passes["location_0"] < 80)
        & (successful_passes["pass_end_location_0"] >= 80)
    ]

    box_entries = successful_passes[
        (successful_passes["pass_end_location_0"] > 102)
        & (successful_passes["pass_end_location_1"] > 18)
        & (successful_passes["pass_end_location_1"] < 62)
    ]

    insights["territorial"] = {
        "defensive_third_passes": len(def_third),
        "middle_third_passes": len(mid_third),
        "attacking_third_passes": len(att_third),
        "final_third_entries": len(final_third_entries),
        "box_entries": len(box_entries),
    }

    # === LEFT/RIGHT BALANCE ===
    left_passes = successful_passes[successful_passes["location_1"] > 40]
    right_passes = successful_passes[successful_passes["location_1"] <= 40]
    left_pct = len(left_passes) / len(successful_passes) * 100 if len(successful_passes) > 0 else 50
    right_pct = len(right_passes) / len(successful_passes) * 100 if len(successful_passes) > 0 else 50

    # === OVER-RELIANCE DETECTION ===
    player_pass_counts = successful_passes["player_name"].value_counts()
    if len(player_pass_counts) > 0:
        top_passer = player_pass_counts.index[0]
        top_passer_pct = player_pass_counts.iloc[0] / len(successful_passes) * 100

        if top_passer_pct > 25:
            insights["vulnerabilities"].append({
                "type": "over_reliance",
                "severity": "high" if top_passer_pct > 35 else "medium",
                "player": get_nickname(top_passer),
                "value": round(top_passer_pct, 1),
                "message": f"Over-reliance on {get_nickname(top_passer)} ({round(top_passer_pct, 1)}% of build-up passes)",
            })

    # === LEFT/RIGHT IMBALANCE ===
    imbalance = abs(left_pct - right_pct)
    if imbalance > 20:
        dominant_side = "left" if left_pct > right_pct else "right"
        insights["vulnerabilities"].append({
            "type": "side_imbalance",
            "severity": "high" if imbalance > 30 else "medium",
            "value": round(imbalance, 1),
            "message": f"Attack heavily favors {dominant_side} side ({round(max(left_pct, right_pct), 1)}% vs {round(min(left_pct, right_pct), 1)}%)",
        })

    # === PRESSURE VULNERABILITY ===
    if len(under_pressure) > min_pressure_situations and pressure_accuracy < 60:
        insights["vulnerabilities"].append({
            "type": "pressure_weakness",
            "severity": "high" if pressure_accuracy < 50 else "medium",
            "value": round(pressure_accuracy, 1),
            "message": f"Struggles under pressure ({round(pressure_accuracy, 1)}% accuracy when pressed)",
        })

    # === STRENGTHS ===
    if progressive_pct > 15:
        insights["strengths"].append({
            "type": "progressive_passing",
            "value": round(progressive_pct, 1),
            "message": f"Strong progressive passing ({round(progressive_pct, 1)}% of passes advance 10+ meters)",
        })

    if pass_accuracy > 85:
        insights["strengths"].append({
            "type": "pass_accuracy",
            "value": round(pass_accuracy, 1),
            "message": f"Excellent pass accuracy ({round(pass_accuracy, 1)}%)",
        })

    if len(box_entries) > 5:
        insights["strengths"].append({
            "type": "box_penetration",
            "value": len(box_entries),
            "message": f"Good penetration into penalty area ({len(box_entries)} entries)",
        })

    if len(under_pressure) > 10 and pressure_accuracy > 75:
        insights["strengths"].append({
            "type": "press_resistance",
            "value": round(pressure_accuracy, 1),
            "message": f"Press resistant ({round(pressure_accuracy, 1)}% accuracy under pressure)",
        })

    # === STRONGEST TRIANGLES ===
    triangle_counts = defaultdict(int)
    for _, row in successful_passes.iterrows():
        passer = row["player_name"]
        recipient = row["pass_recipient_name"]
        if pd.notna(passer) and pd.notna(recipient):
            pair = tuple(sorted([passer, recipient]))
            triangle_counts[pair] += 1

    top_connections = sorted(triangle_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    if top_connections:
        best_pair = top_connections[0]
        insights["strengths"].append({
            "type": "strong_connection",
            "players": [get_nickname(best_pair[0][0]), get_nickname(best_pair[0][1])],
            "value": best_pair[1],
            "message": f"Strong partnership: {get_nickname(best_pair[0][0])} - {get_nickname(best_pair[0][1])} ({best_pair[1]} passes)",
        })

    # === NEW PHASE 1 METRICS ===
    insights["pass_sequences"] = calculate_pass_sequences(df, team_name)
    insights["ppda"] = calculate_ppda(df, team_name)
    insights["pass_directions"] = calculate_pass_directions(df, team_name)
    insights["field_tilt"] = calculate_field_tilt(df, team_name)
    insights["team_shape"] = calculate_team_shape(df, team_name)

    # Advanced Network Metrics
    pass_matrix_adv = defaultdict(lambda: defaultdict(int))
    all_players_adv = list(set(successful_passes["player_name"].dropna().unique()).union(
        set(successful_passes["pass_recipient_name"].dropna().unique())
    ))

    for _, row in successful_passes.iterrows():
        passer = row["player_name"]
        recipient = row["pass_recipient_name"]
        if pd.notna(passer) and pd.notna(recipient):
            pass_matrix_adv[passer][recipient] += 1

    betweenness = calculate_betweenness_centrality(pass_matrix_adv, all_players_adv)
    clustering_vals = calculate_clustering_coefficient(pass_matrix_adv, all_players_adv)
    eigenvector = calculate_eigenvector_centrality(pass_matrix_adv, all_players_adv)

    top_betweenness = sorted(betweenness.items(), key=lambda x: x[1], reverse=True)[:3]
    top_clustering = sorted(clustering_vals.items(), key=lambda x: x[1], reverse=True)[:3]
    top_eigenvector = sorted(eigenvector.items(), key=lambda x: x[1], reverse=True)[:3]

    avg_clustering = sum(clustering_vals.values()) / max(len(clustering_vals), 1)

    insights["advanced_network"] = {
        "top_betweenness": [(get_nickname(p), v) for p, v in top_betweenness],
        "top_clustering": [(get_nickname(p), v) for p, v in top_clustering],
        "top_eigenvector": [(get_nickname(p), v) for p, v in top_eigenvector],
        "avg_clustering_coefficient": round(avg_clustering, 4),
        "network_cohesion": "High" if avg_clustering > 0.5 else ("Medium" if avg_clustering > 0.3 else "Low"),
    }

    # PPDA-based strengths/vulnerabilities
    ppda_val = insights["ppda"].get("ppda", 10)
    if ppda_val < 7:
        insights["strengths"].append({
            "type": "high_press",
            "value": ppda_val,
            "message": f"Elite pressing intensity (PPDA: {ppda_val}) - opponent allowed very few passes before defensive action",
        })
    elif ppda_val > 15:
        insights["vulnerabilities"].append({
            "type": "low_press",
            "severity": "medium",
            "value": ppda_val,
            "message": f"Low pressing intensity (PPDA: {ppda_val}) - opponent given too much time on the ball",
        })

    # Sequence length
    avg_seq = insights["pass_sequences"].get("avg_length", 0)
    if avg_seq > 5:
        insights["strengths"].append({
            "type": "possession_control",
            "value": avg_seq,
            "message": f"Excellent ball retention (avg {avg_seq:.1f} passes per sequence)",
        })
    elif avg_seq < 2.5:
        insights["vulnerabilities"].append({
            "type": "poor_retention",
            "severity": "medium",
            "value": avg_seq,
            "message": f"Poor ball retention (avg {avg_seq:.1f} passes per sequence)",
        })

    # Field tilt
    tilt = insights["field_tilt"].get("field_tilt", 50)
    if tilt > 65:
        insights["strengths"].append({
            "type": "territorial_dominance",
            "value": tilt,
            "message": f"Strong territorial dominance ({tilt:.1f}% of passes in opponent's half)",
        })
    elif tilt < 40:
        insights["vulnerabilities"].append({
            "type": "territorial_weakness",
            "severity": "high",
            "value": tilt,
            "message": f"Poor territorial presence ({tilt:.1f}% of passes in opponent's half)",
        })

    # === PERIOD-SPECIFIC VULNERABILITY ANALYSIS ===
    insights["period_vulnerabilities"] = []

    if period_duration > 60:
        first_half_df = df[df["period"] == 1]
        second_half_df = df[df["period"] == 2]
        half_issues = []

        for half_num, half_df in [(1, first_half_df), (2, second_half_df)]:
            if len(half_df) == 0:
                continue
            half_name = "1st Half" if half_num == 1 else "2nd Half"
            half_team_passes = half_df[(half_df["team_name"] == team_name) & (half_df["event_type"] == "Pass")]
            half_successful = half_team_passes[half_team_passes["pass_outcome_name"].isna()]

            if len(half_successful) == 0:
                continue

            if has_xt_data and "xt_added" in half_successful.columns:
                half_xt = half_successful["xt_added"].sum()
                if half_xt < 0.4:
                    half_issues.append({
                        "period": half_name, "type": "low_xt_generation",
                        "value": round(float(half_xt), 3),
                        "message": f"{half_name}: Only {round(float(half_xt), 3)} xT generated - attack lacked threat",
                    })

            half_total = len(half_team_passes)
            half_accuracy = len(half_successful) / half_total * 100 if half_total > 0 else 0
            if half_accuracy < 70:
                half_issues.append({
                    "period": half_name, "type": "low_accuracy",
                    "value": round(half_accuracy, 1),
                    "message": f"{half_name}: Pass accuracy dropped to {round(half_accuracy, 1)}%",
                })

            half_pressure = half_team_passes[half_team_passes["under_pressure"] == 1.0]
            half_pressure_success = half_pressure[half_pressure["pass_outcome_name"].isna()]
            if len(half_pressure) >= 5:
                half_pressure_acc = len(half_pressure_success) / len(half_pressure) * 100
                if half_pressure_acc < 55:
                    half_issues.append({
                        "period": half_name, "type": "pressure_weakness",
                        "value": round(half_pressure_acc, 1),
                        "message": f"{half_name}: Struggled under pressure ({round(half_pressure_acc, 1)}% accuracy)",
                    })

            half_in_opp = half_successful[half_successful["location_0"] >= 60]
            half_tilt = len(half_in_opp) / len(half_successful) * 100 if len(half_successful) > 0 else 50
            if half_tilt < 35:
                half_issues.append({
                    "period": half_name, "type": "territorial_weakness",
                    "value": round(half_tilt, 1),
                    "message": f"{half_name}: Poor territorial presence ({round(half_tilt, 1)}% in opponent's half)",
                })

        for issue in half_issues:
            insights["period_vulnerabilities"].append(issue)

        if half_issues:
            first_half_issues = [i for i in half_issues if i["period"] == "1st Half"]
            second_half_issues = [i for i in half_issues if i["period"] == "2nd Half"]
            summary_parts = []
            if first_half_issues:
                summary_parts.append(f"1st Half had {len(first_half_issues)} issue(s)")
            if second_half_issues:
                summary_parts.append(f"2nd Half had {len(second_half_issues)} issue(s)")
            insights["period_vulnerability_summary"] = {
                "has_issues": True,
                "total_issues": len(half_issues),
                "first_half_issues": len(first_half_issues),
                "second_half_issues": len(second_half_issues),
                "summary": " | ".join(summary_parts),
                "note": "Full match metrics may mask period-specific weaknesses",
            }
        else:
            insights["period_vulnerability_summary"] = {
                "has_issues": False, "total_issues": 0,
                "summary": "Performance was consistent across both halves",
            }

    # Generate narrative insights
    insights["narrative"] = generate_narrative_insights(
        insights, team_name, pass_accuracy, len(successful_passes)
    )

    return insights


# ---------------------------------------------------------------------------
# NARRATIVE INSIGHTS
# ---------------------------------------------------------------------------
def generate_narrative_insights(insights, team_name, pass_accuracy, total_passes):
    """Professional narrative — matches legacy structure with overview, analysis, recommendations."""
    overview_parts = [
        f"{team_name} completed {total_passes} passes with an accuracy of {pass_accuracy:.1f}%."
    ]

    # Progressive stats
    prog = insights.get("progressive_stats", {})
    prog_pct = prog.get("percentage", 0)
    prog_count = prog.get("count", 0)
    if prog_pct > 18:
        overview_parts.append(f"An impressive {prog_pct}% of passes were progressive ({prog_count} passes advancing 10+ meters).")
    elif prog_pct > 12:
        overview_parts.append(f"{prog_pct}% of passes were progressive, showing good forward intent.")
    elif prog_pct > 0:
        overview_parts.append(f"Only {prog_pct}% of passes were progressive ({prog_count} passes).")

    # Box entries
    terr = insights.get("territorial", {})
    box_entries = terr.get("box_entries", 0)
    if box_entries >= 8:
        overview_parts.append(f"Excellent penalty box penetration with {box_entries} entries.")
    elif box_entries >= 4:
        final_entries = terr.get("final_third_entries", 0)
        if final_entries > 0:
            conversion = round(box_entries / final_entries * 100, 1) if final_entries > 0 else 0
            overview_parts.append(f"{box_entries} penalty box entries from {final_entries} final third entries ({conversion}% conversion).")

    # xT
    xt_stats = insights.get("xt_stats", {})
    if xt_stats.get("has_data"):
        total_xt = xt_stats.get("total_xt", 0)
        if total_xt > 1.5:
            overview_parts.append(f"Generated {total_xt:.3f} total xT, indicating strong attacking threat through passing.")
        elif total_xt > 0.8:
            overview_parts.append(f"Generated {total_xt:.3f} total xT from passing.")

    overview = " ".join(overview_parts)

    # Analysis
    analysis_parts = []

    # xT breakdown
    if xt_stats.get("has_data"):
        xt_zone = xt_stats.get("xt_by_zone", {})
        top_players = xt_stats.get("top_xt_players", [])
        if xt_zone:
            zone_parts = [f"{k}: {v:.3f}" for k, v in sorted(xt_zone.items(), key=lambda x: x[1], reverse=True)]
            analysis_parts.append(f"xT breakdown by zone: {', '.join(zone_parts)}.")
        if top_players:
            player_parts = [f"{p[0]} ({p[1]:.3f})" for p in top_players[:3]]
            analysis_parts.append(f"Top threat creators: {', '.join(player_parts)}.")

    # Territorial
    def_passes = terr.get("defensive_third_passes", 0)
    mid_passes = terr.get("middle_third_passes", 0)
    att_passes = terr.get("attacking_third_passes", 0)
    total_terr = def_passes + mid_passes + att_passes
    if total_terr > 0:
        analysis_parts.append(
            f"Territorial distribution: {round(att_passes/total_terr*100,1)}% attacking, "
            f"{round(mid_passes/total_terr*100,1)}% middle, {round(def_passes/total_terr*100,1)}% defensive third."
        )

    # Pressure
    pressure = insights.get("pressure_stats", {})
    p_acc = pressure.get("pressure_accuracy", 0)
    n_acc = pressure.get("normal_accuracy", 0)
    p_resist = pressure.get("pressure_resistance", 0)
    if pressure.get("passes_under_pressure", 0) > 0:
        analysis_parts.append(
            f"Under pressure: {p_acc}% accuracy vs {n_acc}% normally ({p_resist:+.1f}pp)."
        )

    analysis = " ".join(analysis_parts)

    # Recommendations
    recommendations = []
    # Over-reliance
    for v in insights.get("vulnerabilities", []):
        if v.get("type") == "over_reliance":
            recommendations.append({
                "title": "Diversify Build-up",
                "text": v.get("message", ""),
            })
        elif v.get("type") == "side_imbalance":
            recommendations.append({
                "title": "Balance Width",
                "text": v.get("message", ""),
            })
        elif v.get("type") == "pressure_weakness":
            recommendations.append({
                "title": "Improve Press Resistance",
                "text": v.get("message", ""),
            })
        elif v.get("type") == "low_xt_generation":
            recommendations.append({
                "title": "Increase Attacking Threat",
                "text": v.get("message", ""),
            })

    if prog_pct < 12 and box_entries < 4:
        recommendations.append({
            "title": "Improve Progression",
            "text": f"Low progressive passing ({prog_pct}%) and few box entries ({box_entries}) suggest need for more direct play.",
        })

    if not recommendations:
        recommendations.append({
            "title": "Maintain Approach",
            "text": "Performance was well-balanced with no critical vulnerabilities.",
        })

    return {
        "overview": overview,
        "analysis": analysis,
        "recommendations": recommendations,
    }


# ---------------------------------------------------------------------------
# TIME INTERVALS
# ---------------------------------------------------------------------------
def calculate_time_intervals(df, team_name, interval_minutes=15):
    """Network metrics for each time interval — matches legacy."""
    intervals = []
    max_minute = int(df["minute"].max()) if not df["minute"].isna().all() else 90

    for start in range(0, max_minute + 1, interval_minutes):
        end = min(start + interval_minutes, max_minute + 1)
        interval_df = df[(df["minute"] >= start) & (df["minute"] < end)]

        if len(interval_df) == 0:
            continue

        network = calculate_network_metrics(interval_df, team_name)

        if network:
            metrics = network.get("metrics", {})
            intervals.append({
                "start": start,
                "end": end,
                "label": f"{start}'-{end}'",
                "total_passes": metrics.get("total_passes", 0),
                "density": metrics.get("network_density", 0),
                "hub": get_nickname(metrics["hub_player"]) if metrics.get("hub_player") else None,
            })

    return intervals


# ---------------------------------------------------------------------------
# THOMAS GRUND CENTRALITY
# ---------------------------------------------------------------------------
def calculate_thomas_grund_centrality(df, team_name, network_data=None):
    """
    Matches legacy api_server.py calculate_thomas_grund_centrality exactly.
    Total involvement per player. Hub = max involvement.
    Centrality = sum_of_differences / (n * total_passes).
    """
    if network_data is None:
        network_data = calculate_network_metrics(df, team_name)

    if not network_data or "players" not in network_data:
        return None

    players = network_data["players"]
    if len(players) < 2:
        return None

    # Build involvement from network data — matches legacy
    player_involvement = {}
    total_passes = 0
    for p in players:
        player_involvement[p["name"]] = {
            "passes_made": p.get("passes_made", 0),
            "passes_received": p.get("passes_received", 0),
            "total_involvement": p.get("total_involvement", 0),
        }
        total_passes += p.get("passes_made", 0)

    if len(player_involvement) < 2:
        return None

    hub_player = max(player_involvement.items(), key=lambda x: x[1]["total_involvement"])
    max_involvement = hub_player[1]["total_involvement"]
    hub_name = hub_player[0]

    differences = []
    for player_name, stats in player_involvement.items():
        diff = max_involvement - stats["total_involvement"]
        differences.append(diff)
        player_involvement[player_name]["difference_from_hub"] = diff

    n = len(player_involvement)
    sum_differences = sum(differences)

    centrality_score = sum_differences / (n * total_passes) if total_passes > 0 else 0
    centrality_percentage = round(centrality_score * 100, 2)

    # Style classification — legacy uses Title Case
    if centrality_percentage < 12:
        style = "Highly Decentralized"
        style_description = "Ball shared evenly across the team"
    elif centrality_percentage < 18:
        style = "Moderately Decentralized"
        style_description = "Good balance with slight hub tendencies"
    elif centrality_percentage < 25:
        style = "Moderately Centralized"
        style_description = "Clear playmaker orchestrating the build-up"
    else:
        style = "Highly Centralized"
        style_description = "Heavy reliance on one player for ball circulation"

    sorted_players = sorted(
        player_involvement.items(),
        key=lambda x: x[1]["total_involvement"],
        reverse=True,
    )

    hub_stats = player_involvement[hub_name]

    # Orchestration narrative — matches legacy multi-part format
    orchestration_parts = []
    orchestration_parts.append(
        f"{team_name}'s passing network has a Thomas Grund centrality index of "
        f"{centrality_percentage}%, classifying it as {style}."
    )
    orchestration_parts.append(
        f"The hub player is {get_nickname(hub_name)} with {max_involvement} total involvements "
        f"out of {total_passes} total passes among {n} players."
    )

    if style == "Highly Decentralized":
        orchestration_parts.append(
            "The team distributes the ball very evenly, with no single player "
            "dominating possession. This makes them harder to disrupt by "
            "marking a single player."
        )
    elif style == "Moderately Decentralized":
        orchestration_parts.append(
            "The team has a fairly balanced distribution of passes, with the "
            "hub player being slightly more involved but not dominant."
        )
    elif style == "Moderately Centralized":
        orchestration_parts.append(
            "The team channels a significant portion of play through their hub "
            "player. This can be effective but creates a vulnerability if the "
            "hub is pressed or isolated."
        )
    else:
        orchestration_parts.append(
            "The team is heavily reliant on their hub player for ball "
            "distribution. Opposition could exploit this by pressing or "
            "isolating this player."
        )

    return {
        "centrality_score": centrality_score,
        "centrality_percentage": centrality_percentage,
        "style": style,
        "style_description": style_description,
        "hub_player": {
            "name": hub_name,
            "nickname": get_nickname(hub_name),
            "passes_made": hub_stats["passes_made"],
            "passes_received": hub_stats["passes_received"],
            "total_involvement": hub_stats["total_involvement"],
        },
        "player_rankings": [
            {
                "rank": i + 1,
                "name": p[0],
                "nickname": get_nickname(p[0]),
                "passes_made": p[1]["passes_made"],
                "passes_received": p[1]["passes_received"],
                "total_involvement": p[1]["total_involvement"],
                "difference_from_hub": p[1]["difference_from_hub"],
            }
            for i, p in enumerate(sorted_players[:10])
        ],
        "orchestration": " ".join(orchestration_parts),
        "total_passes": total_passes,
        "num_players": n,
    }


# ---------------------------------------------------------------------------
# PASSING RATE
# ---------------------------------------------------------------------------
def calculate_passing_rate(df, team_name):
    """Passes per minute — matches legacy: successful passes only, team event time range."""
    team_passes = df[
        (df["team_name"] == team_name)
        & (df["event_type"] == "Pass")
        & (df["pass_outcome_name"].isna())
    ]

    if len(team_passes) == 0:
        return None

    team_events = df[df["team_name"] == team_name]
    if len(team_events) == 0:
        return None

    min_minute = team_events["minute"].min()
    max_minute = team_events["minute"].max()
    total_match_minutes = max_minute - min_minute + 1 if pd.notna(max_minute) else 90

    all_passes = df[
        (df["event_type"] == "Pass")
        & (df["pass_outcome_name"].isna())
    ]

    total_all_passes = len(all_passes)
    team_total_passes = len(team_passes)

    possession_ratio = team_total_passes / total_all_passes if total_all_passes > 0 else 0.5
    estimated_possession_minutes = total_match_minutes * possession_ratio

    passes_per_minute = team_total_passes / estimated_possession_minutes if estimated_possession_minutes > 0 else 0

    if passes_per_minute >= 5:
        rating = "Elite"
        interpretation = "High passing tempo indicates strong ball circulation"
    elif passes_per_minute >= 4:
        rating = "Above Average"
        interpretation = "Good tempo with solid ball circulation"
    elif passes_per_minute >= 3:
        rating = "Average"
        interpretation = "Moderate passing tempo"
    else:
        rating = "Below Average"
        interpretation = "Slow tempo"

    return {
        "passes_per_minute": round(passes_per_minute, 2),
        "total_passes": team_total_passes,
        "estimated_possession_minutes": round(estimated_possession_minutes, 1),
        "possession_percentage": round(possession_ratio * 100, 1),
        "rating": rating,
        "interpretation": interpretation,
        "benchmark": {
            "elite": 5.0,
            "average": 3.5,
            "description": "Higher passing tempo indicates stronger ball circulation",
        },
    }


# ---------------------------------------------------------------------------
# TACTICAL MAP 25 ZONES
# ---------------------------------------------------------------------------
def calculate_tactical_map_25_zones(df, team_name):
    """
    Calculate pass distribution map with 25 zones (5x5 grid).
    Matches legacy: only successful passes, col=x-axis, row=y-axis.
    """
    team_passes = df[
        (df["team_name"] == team_name)
        & (df["event_type"] == "Pass")
        & (df["pass_outcome_name"].isna())
        & (df["location_0"].notna())
        & (df["pass_end_location_0"].notna())
    ]

    if len(team_passes) == 0:
        return None

    x_step = 120 / 5
    y_step = 80 / 5

    zones = {}

    for row in range(5):  # y-axis
        for col in range(5):  # x-axis
            zone_id = f"{row}_{col}"

            x_min = col * x_step
            x_max = (col + 1) * x_step
            y_min = row * y_step
            y_max = (row + 1) * y_step

            zone_passes = team_passes[
                (team_passes["location_0"] >= x_min)
                & (team_passes["location_0"] < x_max)
                & (team_passes["location_1"] >= y_min)
                & (team_passes["location_1"] < y_max)
            ]

            if len(zone_passes) == 0:
                zones[zone_id] = {
                    "row": row,
                    "col": col,
                    "count": 0,
                    "center_x": (x_min + x_max) / 2,
                    "center_y": (y_min + y_max) / 2,
                    "avg_direction": 0,
                    "avg_distance": 0,
                    "intensity": 0,
                }
                continue

            dx_values = zone_passes["pass_end_location_0"] - zone_passes["location_0"]
            dy_values = zone_passes["pass_end_location_1"] - zone_passes["location_1"]

            avg_dx = dx_values.mean()
            avg_dy = dy_values.mean()
            avg_direction = math.degrees(math.atan2(avg_dy, avg_dx))
            distances = np.sqrt(dx_values**2 + dy_values**2)
            avg_distance = distances.mean()

            zones[zone_id] = {
                "row": row,
                "col": col,
                "count": len(zone_passes),
                "center_x": (x_min + x_max) / 2,
                "center_y": (y_min + y_max) / 2,
                "avg_direction": round(avg_direction, 1),
                "avg_distance": round(avg_distance, 1),
                "avg_dx": round(float(avg_dx), 2),
                "avg_dy": round(float(avg_dy), 2),
                "intensity": 0,
            }

    max_count = max(z["count"] for z in zones.values()) or 1
    for zone_id in zones:
        zones[zone_id]["intensity"] = round(zones[zone_id]["count"] / max_count, 3)

    zone_labels = {
        (0, 0): "Left Defensive", (0, 1): "Left Deep", (0, 2): "Left Middle",
        (0, 3): "Left Advanced", (0, 4): "Left Final Third",
        (1, 0): "Center-Left Defensive", (1, 1): "Center-Left Deep", (1, 2): "Center-Left Middle",
        (1, 3): "Center-Left Advanced", (1, 4): "Center-Left Final Third",
        (2, 0): "Central Defensive", (2, 1): "Central Deep", (2, 2): "Central Middle",
        (2, 3): "Central Advanced", (2, 4): "Central Final Third",
        (3, 0): "Center-Right Defensive", (3, 1): "Center-Right Deep", (3, 2): "Center-Right Middle",
        (3, 3): "Center-Right Advanced", (3, 4): "Center-Right Final Third",
        (4, 0): "Right Defensive", (4, 1): "Right Deep", (4, 2): "Right Middle",
        (4, 3): "Right Advanced", (4, 4): "Right Final Third",
    }

    for zone_id, zone_data in zones.items():
        r, c = zone_data["row"], zone_data["col"]
        zones[zone_id]["label"] = zone_labels.get((r, c), f"Zone {r},{c}")

    sorted_zones = sorted(zones.values(), key=lambda x: x["count"], reverse=True)

    return {
        "zones": zones,
        "grid_size": 5,
        "hotspots": sorted_zones[:5],
        "total_passes": len(team_passes),
        "max_zone_count": max_count,
    }


# ---------------------------------------------------------------------------
# ZONE PASS DIRECTIONS
# ---------------------------------------------------------------------------
def calculate_zone_pass_directions(df, team_name):
    """25 zones pass direction sonar — matches legacy: successful passes, radians, col=x row=y."""
    team_passes = df[
        (df["team_name"] == team_name)
        & (df["event_type"] == "Pass")
        & (df["pass_outcome_name"].isna())
        & (df["location_0"].notna())
        & (df["pass_end_location_0"].notna())
    ]

    if len(team_passes) == 0:
        return None

    zone_width = 24
    zone_height = 16

    zones = {}
    max_passes_in_zone = 0

    for row in range(5):
        for col in range(5):
            zone_id = row * 5 + col
            zone_x_min = col * zone_width
            zone_x_max = (col + 1) * zone_width
            zone_y_min = row * zone_height
            zone_y_max = (row + 1) * zone_height

            center_x = zone_x_min + zone_width / 2
            center_y = zone_y_min + zone_height / 2

            zone_passes = team_passes[
                (team_passes["location_0"] >= zone_x_min)
                & (team_passes["location_0"] < zone_x_max)
                & (team_passes["location_1"] >= zone_y_min)
                & (team_passes["location_1"] < zone_y_max)
            ]

            pass_vectors = []
            for _, p in zone_passes.iterrows():
                dx = p["pass_end_location_0"] - p["location_0"]
                dy = p["pass_end_location_1"] - p["location_1"]
                angle = math.atan2(dy, dx)  # Radians
                distance = math.sqrt(dx * dx + dy * dy)
                pass_vectors.append({"angle": round(angle, 3), "distance": round(distance, 1)})

            total_zone_passes = len(zone_passes)
            max_passes_in_zone = max(max_passes_in_zone, total_zone_passes)

            # 16-bin direction summary (legacy uses radians normalization)
            dir_bins = [0] * 16
            for pv in pass_vectors:
                normalized = (pv["angle"] + math.pi) / (2 * math.pi)
                bin_idx = int(normalized * 16) % 16
                dir_bins[bin_idx] += 1

            zones[zone_id] = {
                "row": row,
                "col": col,
                "center_x": center_x,
                "center_y": center_y,
                "total_passes": total_zone_passes,
                "pass_vectors": pass_vectors,
                "direction_bins": dir_bins,
            }

    max_distance = 0
    for zone in zones.values():
        for pv in zone["pass_vectors"]:
            max_distance = max(max_distance, pv["distance"])

    return {
        "zones": zones,
        "max_passes_in_zone": max_passes_in_zone,
        "max_distance": max_distance,
        "total_passes": len(team_passes),
    }


# ---------------------------------------------------------------------------
# ZONE CONNECTIONS
# ---------------------------------------------------------------------------
def calculate_zone_connections(df, team_name, min_passes=1):
    """Zone-to-zone pass connections — matches legacy: successful passes, col=x-axis progression."""
    team_passes = df[
        (df["team_name"] == team_name)
        & (df["event_type"] == "Pass")
        & (df["pass_outcome_name"].isna())
        & (df["location_0"].notna())
        & (df["pass_end_location_0"].notna())
    ]

    if len(team_passes) == 0:
        return None

    zone_width = 24
    zone_height = 16

    def get_zone(x, y):
        col = min(int(x / zone_width), 4)
        row = min(int(y / zone_height), 4)
        return row * 5 + col

    zone_connections = {}
    zone_activity = {}
    same_zone_passes = 0

    for _, p in team_passes.iterrows():
        source_zone = get_zone(p["location_0"], p["location_1"])
        target_zone = get_zone(p["pass_end_location_0"], p["pass_end_location_1"])

        zone_activity[source_zone] = zone_activity.get(source_zone, 0) + 1
        if source_zone != target_zone:
            zone_activity[target_zone] = zone_activity.get(target_zone, 0) + 1

        if source_zone == target_zone:
            same_zone_passes += 1
            continue

        conn_key = (source_zone, target_zone)
        if conn_key not in zone_connections:
            zone_connections[conn_key] = {
                "source": source_zone,
                "target": target_zone,
                "count": 0,
                "progressive": 0,
                "regressive": 0,
                "lateral": 0,
            }

        zone_connections[conn_key]["count"] += 1

        # Column determines direction: higher column = toward opponent's goal.
        # progressive  = target column further from own goal
        # regressive   = target column closer to own goal
        # lateral      = same column but a different row (sideways pass at
        #                the same depth). Same-zone passes are filtered out
        #                a few lines above via the `continue`, so reaching
        #                this point with source_col == target_col always
        #                means a sideways pass between different rows.
        source_col = source_zone % 5
        target_col = target_zone % 5
        if target_col > source_col:
            zone_connections[conn_key]["progressive"] += 1
        elif target_col < source_col:
            zone_connections[conn_key]["regressive"] += 1
        else:
            zone_connections[conn_key]["lateral"] += 1

    edges = [conn for conn in zone_connections.values() if conn["count"] >= min_passes]
    edges.sort(key=lambda x: x["count"], reverse=True)

    zone_names = {
        0: "Def L", 1: "Deep L", 2: "Mid L", 3: "Adv L", 4: "Att L",
        5: "Def LC", 6: "Deep LC", 7: "Mid LC", 8: "Adv LC", 9: "Att LC",
        10: "Def C", 11: "Deep C", 12: "Mid C", 13: "Adv C", 14: "Att C",
        15: "Def RC", 16: "Deep RC", 17: "Mid RC", 18: "Adv RC", 19: "Att RC",
        20: "Def R", 21: "Deep R", 22: "Mid R", 23: "Adv R", 24: "Att R",
    }

    nodes = []
    for zone_id in range(25):
        row = zone_id // 5
        col = zone_id % 5
        center_x = (col + 0.5) * zone_width
        center_y = (row + 0.5) * zone_height
        activity = zone_activity.get(zone_id, 0)
        nodes.append({
            "id": zone_id,
            "name": zone_names[zone_id],
            "row": row,
            "col": col,
            "x": center_x,
            "y": center_y,
            "activity": activity,
        })

    max_activity = max([n["activity"] for n in nodes], default=1)
    max_connection = max([e["count"] for e in edges], default=1)

    zone_to_zone_connections = sum(e["count"] for e in edges)
    progressive_total = sum(e["progressive"] for e in edges)
    regressive_total = sum(e["regressive"] for e in edges)
    total_connections = zone_to_zone_connections + same_zone_passes
    lateral_from_edges = zone_to_zone_connections - progressive_total - regressive_total
    lateral_total = lateral_from_edges + same_zone_passes

    top_corridors = edges[:10] if len(edges) >= 10 else edges
    busiest_zones = sorted(nodes, key=lambda x: x["activity"], reverse=True)[:5]

    return {
        "nodes": nodes,
        "edges": edges,
        "max_activity": max_activity,
        "max_connection": max_connection,
        "total_connections": total_connections,
        "progressive_passes": progressive_total,
        "regressive_passes": regressive_total,
        "lateral_passes": lateral_total,
        "same_zone_passes": same_zone_passes,
        "top_corridors": top_corridors,
        "busiest_zones": busiest_zones,
    }


# ---------------------------------------------------------------------------
# SHOT MAP
# ---------------------------------------------------------------------------
def calculate_shot_map(df, team_name):
    """Shots grouped by player with xG, goals, conversion rate, xG difference."""
    shots = df[
        (df["team_name"] == team_name) & (df["event_type"] == "Shot")
    ]

    if len(shots) == 0:
        return {"players": [], "total_shots": 0, "total_xg": 0, "total_goals": 0}

    player_shots = defaultdict(
        lambda: {"shots": 0, "goals": 0, "xg": 0.0, "details": []}
    )

    for _, s in shots.iterrows():
        player = s.get("player_name", "Unknown")
        if pd.isna(player):
            player = "Unknown"

        xg = float(s.get("shot_statsbomb_xg", 0)) if not pd.isna(s.get("shot_statsbomb_xg", None)) else 0
        outcome = s.get("shot_outcome_name", "")
        is_goal = 1 if outcome == "Goal" else 0

        player_shots[player]["shots"] += 1
        player_shots[player]["goals"] += is_goal
        player_shots[player]["xg"] += xg
        player_shots[player]["details"].append(
            {
                "x": float(s.get("location_0", 0)) if not pd.isna(s.get("location_0", None)) else 0,
                "y": float(s.get("location_1", 0)) if not pd.isna(s.get("location_1", None)) else 0,
                "xg": round(xg, 4),
                "outcome": str(outcome) if not pd.isna(outcome) else "",
                "minute": int(s.get("minute", 0)) if not pd.isna(s.get("minute", None)) else 0,
            }
        )

    result_players = []
    total_shots = 0
    total_xg = 0.0
    total_goals = 0

    for player, data in player_shots.items():
        conv = round(data["goals"] / data["shots"] * 100, 1) if data["shots"] > 0 else 0
        xg_diff = round(data["goals"] - data["xg"], 3)
        result_players.append(
            {
                "player": player,
                "nickname": get_nickname(player),
                "shots": data["shots"],
                "goals": data["goals"],
                "xg": round(data["xg"], 4),
                "conversion_rate": conv,
                "xg_difference": xg_diff,
                "details": data["details"],
            }
        )
        total_shots += data["shots"]
        total_xg += data["xg"]
        total_goals += data["goals"]

    result_players.sort(key=lambda x: x["xg"], reverse=True)

    return {
        "players": result_players,
        "total_shots": total_shots,
        "total_xg": round(total_xg, 4),
        "total_goals": total_goals,
    }


# ---------------------------------------------------------------------------
# OPPONENT PROFILE (multi-match aggregation)
# ---------------------------------------------------------------------------
def calculate_opponent_profile(team_name):
    """
    Aggregate a team's tactical identity across EVERY match in MATCH_DATA
    that features them — average PPDA, field tilt, network density, and
    Thomas Grund centralisation, plus which player shows up as hub most
    often and a per-match trend list (for charting PPDA/tilt/density over
    time). This is what turns single-match analysis into opponent scouting:
    "how does this team usually play", not just "how did they play once".

    Reuses calculate_network_metrics / calculate_ppda / calculate_field_tilt /
    calculate_team_shape / calculate_thomas_grund_centrality per match —
    no new per-match logic, just looping + averaging what already exists.
    """
    matches = []
    for match_date, mdf in MATCH_DATA.items():
        teams_in_match = mdf["team_name"].dropna().unique().tolist()
        if team_name not in teams_in_match:
            continue

        network = calculate_network_metrics(mdf, team_name)
        if network is None:
            continue

        ppda = calculate_ppda(mdf, team_name)
        field_tilt = calculate_field_tilt(mdf, team_name)
        shape = calculate_team_shape(mdf, team_name)
        grund = calculate_thomas_grund_centrality(mdf, team_name, network)

        opponent = [t for t in teams_in_match if t != team_name and pd.notna(t)]
        opponent_name = opponent[0] if opponent else None

        nm = network.get("metrics", {})
        hub_name = nm.get("hub_player")

        matches.append({
            "match_date": match_date,
            "opponent": opponent_name,
            "ppda": ppda.get("ppda"),
            "field_tilt": field_tilt.get("field_tilt"),
            "density": nm.get("network_density"),
            "hub": get_nickname(hub_name) if hub_name else None,
            "centrality_percentage": grund.get("centrality_percentage") if grund else None,
            "style": grund.get("style") if grund else None,
            "avg_width": shape.get("avg_width"),
            "avg_depth": shape.get("avg_depth"),
            "compactness": shape.get("compactness"),
        })

    if not matches:
        return None

    def _avg(key):
        vals = [m[key] for m in matches if m.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    # Most frequent hub player and playing style across matches
    hub_counts = defaultdict(int)
    style_counts = defaultdict(int)
    for m in matches:
        if m.get("hub"):
            hub_counts[m["hub"]] += 1
        if m.get("style"):
            style_counts[m["style"]] += 1

    most_common_hub = max(hub_counts.items(), key=lambda x: x[1])[0] if hub_counts else None
    most_common_style = max(style_counts.items(), key=lambda x: x[1])[0] if style_counts else None

    avg_ppda = _avg("ppda")
    avg_tilt = _avg("field_tilt")
    avg_density = _avg("density")
    avg_centrality = _avg("centrality_percentage")

    # Plain-language scouting takeaways derived straight from the averages
    takeaways = []
    if avg_ppda is not None:
        if avg_ppda < 8:
            takeaways.append(
                f"Presses high on average (PPDA {avg_ppda}) - expect them to close down "
                f"quickly; look to play direct and bypass the press rather than build slowly."
            )
        elif avg_ppda > 14:
            takeaways.append(
                f"Presses passively on average (PPDA {avg_ppda}) - time on the ball should "
                f"be available in build-up phases."
            )
    if avg_tilt is not None:
        if avg_tilt > 58:
            takeaways.append(
                f"Typically dominates territory (avg field tilt {avg_tilt}%) - be prepared "
                f"to defend for long spells and look to hit them on the counter."
            )
        elif avg_tilt < 42:
            takeaways.append(
                f"Tends to concede territory (avg field tilt {avg_tilt}%) - they may sit "
                f"deep or rely on quick transitions rather than sustained pressure."
            )
    if avg_centrality is not None and most_common_hub:
        if avg_centrality >= 18:
            takeaways.append(
                f"Build-up regularly runs through {most_common_hub} (avg centralisation "
                f"{avg_centrality}%) - cutting off their supply disrupts the whole team."
            )
        else:
            takeaways.append(
                f"Passing is fairly evenly distributed (avg centralisation {avg_centrality}%) "
                f"- no single player to isolate; pressing has to be a team effort."
            )
    if not takeaways:
        takeaways.append("Not enough consistent signal yet across these matches to draw a strong tactical pattern.")

    matches.sort(key=lambda m: m["match_date"])

    return {
        "team": team_name,
        "matches_analyzed": len(matches),
        "averages": {
            "ppda": avg_ppda,
            "field_tilt": avg_tilt,
            "density": avg_density,
            "centrality_percentage": avg_centrality,
            "avg_width": _avg("avg_width"),
            "avg_depth": _avg("avg_depth"),
            "compactness": _avg("compactness"),
        },
        "most_common_hub": most_common_hub,
        "most_common_style": most_common_style,
        "takeaways": takeaways,
        "trend": matches,
    }


# ---------------------------------------------------------------------------
# PLAYER PROFILE (multi-match aggregation)
# ---------------------------------------------------------------------------
def calculate_player_profile(player_name):
    """
    Aggregate one player's performance across EVERY match they appear in —
    reuses calculate_player_detail per match (same function handle_player
    already calls for a single match) and sums/averages the results, plus
    builds a per-match trend so form/consistency is visible, not just a
    single-game snapshot. This is the player-side counterpart to
    calculate_opponent_profile above.
    """
    matches = []
    for match_date, mdf in MATCH_DATA.items():
        appears = (
            (mdf["player_name"] == player_name).any()
            or ("pass_recipient_name" in mdf.columns and (mdf["pass_recipient_name"] == player_name).any())
        )
        if not appears:
            continue

        detail = calculate_player_detail(mdf, player_name)
        team = detail.get("team")
        teams_in_match = mdf["team_name"].dropna().unique().tolist()
        opponent = [t for t in teams_in_match if t != team and pd.notna(t)]
        opponent_name = opponent[0] if opponent else None

        matches.append({
            "match_date": match_date,
            "opponent": opponent_name,
            "team": team,
            "passes_attempted": detail.get("passes_attempted", 0),
            "passes_completed": detail.get("passes_completed", 0),
            "accuracy": detail.get("accuracy"),
            "progressive_passes": detail.get("progressive_passes", 0),
            "under_pressure_accuracy": detail.get("under_pressure_accuracy"),
            "xt_generated": detail.get("xt_generated"),
            "xt_received": detail.get("xt_received"),
        })

    if not matches:
        return None

    def _sum(key):
        return sum((m.get(key) or 0) for m in matches)

    def _avg(key):
        vals = [m[key] for m in matches if m.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    total_attempted = _sum("passes_attempted")
    total_completed = _sum("passes_completed")
    overall_accuracy = round(total_completed / total_attempted * 100, 1) if total_attempted > 0 else None

    # Most frequent team (handles a player appearing for one team across the dataset)
    team_counts = defaultdict(int)
    for m in matches:
        if m.get("team"):
            team_counts[m["team"]] += 1
    primary_team = max(team_counts.items(), key=lambda x: x[1])[0] if team_counts else None

    avg_accuracy = _avg("accuracy")
    avg_xt = _avg("xt_generated")
    avg_progressive = _avg("progressive_passes")
    avg_pressure_acc = _avg("under_pressure_accuracy")

    takeaways = []
    if avg_accuracy is not None:
        if avg_accuracy >= 88:
            takeaways.append(f"Very reliable in possession (avg {avg_accuracy}% pass accuracy) - a safe out-ball under pressure.")
        elif avg_accuracy < 72:
            takeaways.append(f"Below-average accuracy (avg {avg_accuracy}%) - a realistic press target to force turnovers.")
    if avg_pressure_acc is not None:
        if avg_pressure_acc < 55:
            takeaways.append(f"Accuracy drops sharply under pressure (avg {avg_pressure_acc}%) - close them down quickly on the ball.")
        elif avg_pressure_acc >= 80:
            takeaways.append(f"Composed under pressure (avg {avg_pressure_acc}% accuracy) - pressing them individually has limited payoff.")
    if avg_xt is not None:
        if avg_xt > 0.15:
            takeaways.append(f"Consistently generates threat with the ball (avg xT {avg_xt}/match) - a key creative outlet to nullify.")
        elif avg_xt < 0:
            takeaways.append(f"Passing tends to reduce team threat on average (avg xT {avg_xt}/match).")
    if not takeaways:
        takeaways.append("Not enough consistent signal yet across these matches to draw a strong pattern.")

    matches.sort(key=lambda m: m["match_date"])

    return {
        "player": player_name,
        "nickname": get_nickname(player_name),
        "team": primary_team,
        "matches_analyzed": len(matches),
        "totals": {
            "passes_attempted": total_attempted,
            "passes_completed": total_completed,
            "accuracy": overall_accuracy,
            "progressive_passes": _sum("progressive_passes"),
            "xt_generated": round(_sum("xt_generated"), 4),
            "xt_received": round(_sum("xt_received"), 4),
        },
        "averages": {
            "accuracy": avg_accuracy,
            "progressive_passes": avg_progressive,
            "under_pressure_accuracy": avg_pressure_acc,
            "xt_generated": avg_xt,
        },
        "takeaways": takeaways,
        "trend": matches,
    }


# ---------------------------------------------------------------------------
# MATCH VERDICT
# ---------------------------------------------------------------------------
def calculate_match_verdict(df, teams, periods):
    """Matches legacy api_server.py calculate_match_verdict exactly.
    Uses period data for xT, possession, progressive passes, and tempo."""
    if len(teams) < 2:
        return None

    team1, team2 = teams[0], teams[1]
    verdict = {
        "teams": {},
        "comparison": {},
        "verdict_type": "",
        "verdict_headline": "",
        "justice_score": 50,
        "narrative": "",
    }

    for team in [team1, team2]:
        # Goals
        team_goals = df[
            (df["team_name"] == team)
            & (df["event_type"] == "Shot")
            & (df["shot_outcome_name"] == "Goal")
        ]
        goals = len(team_goals)

        # xG
        team_shots = df[
            (df["team_name"] == team) & (df["event_type"] == "Shot")
        ]
        total_xg = team_shots["shot_statsbomb_xg"].sum() if "shot_statsbomb_xg" in team_shots.columns else 0
        total_xg = round(float(total_xg) if pd.notna(total_xg) else 0, 2)

        # Passes — legacy uses only isna() for success
        team_passes = df[
            (df["team_name"] == team) & (df["event_type"] == "Pass")
        ]
        total_passes = len(team_passes)
        successful_passes = len(team_passes[team_passes["pass_outcome_name"].isna()])
        pass_accuracy = round(successful_passes / total_passes * 100, 1) if total_passes > 0 else 0

        # xT from periods — matches legacy
        total_xt = 0
        for period in periods:
            team_data = period["teams"].get(team, {})
            total_xt += team_data.get("xt_added", 0)
        total_xt = round(total_xt, 3)

        # Possession from periods — legacy: weighted average by passes
        total_possession_weight = 0
        possession_sum = 0
        for period in periods:
            team_data = period["teams"].get(team, {})
            poss = team_data.get("possession", 0)
            passes = team_data.get("passes", 0)
            possession_sum += poss * passes
            total_possession_weight += passes
        avg_possession = round(possession_sum / total_possession_weight, 1) if total_possession_weight > 0 else 50

        # Progressive passes from periods — legacy: estimated from territory
        progressive_passes = 0
        for period in periods:
            team_data = period["teams"].get(team, {})
            territory = team_data.get("territory", {})
            attacking_pct = territory.get("attacking", 0)
            passes_in_period = team_data.get("passes", 0)
            progressive_passes += int(passes_in_period * attacking_pct / 100)

        # Tempo — legacy: successful passes / periods with possession > 50%
        periods_with_possession = sum(1 for p in periods if p["teams"].get(team, {}).get("possession", 0) > 50)
        tempo = round(successful_passes / max(periods_with_possession, 1), 1)

        verdict["teams"][team] = {
            "goals": goals,
            "xg": total_xg,
            "xg_diff": round(goals - total_xg, 2),
            "total_xt": total_xt,
            "passes": successful_passes,
            "pass_accuracy": pass_accuracy,
            "possession": avg_possession,
            "progressive_passes": progressive_passes,
            "tempo": tempo,
        }

    t1_data = verdict["teams"][team1]
    t2_data = verdict["teams"][team2]
    t1_goals = t1_data["goals"]
    t2_goals = t2_data["goals"]

    if t1_goals > t2_goals:
        winner, loser = team1, team2
        winner_data, loser_data = t1_data, t2_data
    elif t2_goals > t1_goals:
        winner, loser = team2, team1
        winner_data, loser_data = t2_data, t1_data
    else:
        winner, loser = None, None
        winner_data, loser_data = t1_data, t2_data

    # Comparison metrics — matches legacy thresholds
    xg_diff = t1_data["xg"] - t2_data["xg"]
    xt_diff = t1_data["total_xt"] - t2_data["total_xt"]
    poss_diff = t1_data["possession"] - t2_data["possession"]
    pass_diff = t1_data["passes"] - t2_data["passes"]

    verdict["comparison"] = {
        "xg_advantage": team1 if xg_diff > 0.1 else (team2 if xg_diff < -0.1 else "Even"),
        "xg_diff": round(abs(xg_diff), 2),
        "xt_advantage": team1 if xt_diff > 0.05 else (team2 if xt_diff < -0.05 else "Even"),
        "xt_diff": round(abs(xt_diff), 3),
        "possession_advantage": team1 if poss_diff > 5 else (team2 if poss_diff < -5 else "Even"),
        "possession_diff": round(abs(poss_diff), 1),
        "pass_advantage": team1 if pass_diff > 30 else (team2 if pass_diff < -30 else "Even"),
        "pass_diff": abs(pass_diff),
    }

    if winner:
        # Count metrics favoring winner — matches legacy
        metrics_favoring_winner = 0
        if verdict["comparison"]["xg_advantage"] == winner:
            metrics_favoring_winner += 1
        if verdict["comparison"]["xt_advantage"] == winner:
            metrics_favoring_winner += 1
        if verdict["comparison"]["possession_advantage"] == winner:
            metrics_favoring_winner += 1
        if verdict["comparison"]["pass_advantage"] == winner:
            metrics_favoring_winner += 1

        metrics_favoring_loser = 0
        if verdict["comparison"]["xg_advantage"] == loser:
            metrics_favoring_loser += 1
        if verdict["comparison"]["xt_advantage"] == loser:
            metrics_favoring_loser += 1
        if verdict["comparison"]["possession_advantage"] == loser:
            metrics_favoring_loser += 1
        if verdict["comparison"]["pass_advantage"] == loser:
            metrics_favoring_loser += 1

        verdict["justice_score"] = int(25 + (metrics_favoring_winner * 18.75))

        # Verdict type — matches legacy logic using winner_xg_diff
        winner_xg_diff = winner_data["xg_diff"]  # Goals - xG

        if metrics_favoring_winner >= 3:
            if winner_xg_diff > 0.5:
                verdict["verdict_type"] = "clinical_domination"
                verdict["verdict_headline"] = "Clinical Domination"
            else:
                verdict["verdict_type"] = "deserved_victory"
                verdict["verdict_headline"] = "Deserved Victory"
        elif metrics_favoring_winner >= 2:
            if winner_xg_diff > 0.5:
                verdict["verdict_type"] = "efficient_win"
                verdict["verdict_headline"] = "Efficient Victory"
            else:
                verdict["verdict_type"] = "balanced_win"
                verdict["verdict_headline"] = "Competitive Victory"
        elif metrics_favoring_loser >= 3:
            if loser_data["xg"] - winner_data["xg"] > 0.5:
                verdict["verdict_type"] = "smash_and_grab"
                verdict["verdict_headline"] = "Smash & Grab"
            else:
                verdict["verdict_type"] = "against_the_odds"
                verdict["verdict_headline"] = "Against The Odds"
        else:
            if winner_xg_diff > 1:
                verdict["verdict_type"] = "lucky_escape"
                verdict["verdict_headline"] = "Lucky Victory"
            else:
                verdict["verdict_type"] = "tight_margins"
                verdict["verdict_headline"] = "Fine Margins"

        # Generate narrative — matches legacy
        narrative_parts = []
        if verdict["verdict_type"] in ["deserved_victory", "clinical_domination"]:
            narrative_parts.append(f"{winner} earned their victory with a commanding performance.")
        elif verdict["verdict_type"] == "smash_and_grab":
            narrative_parts.append(f"{winner} pulled off a classic smash-and-grab despite {loser}'s dominance.")
        elif verdict["verdict_type"] == "against_the_odds":
            narrative_parts.append(f"{winner} defied the statistics to claim victory.")
        elif verdict["verdict_type"] == "lucky_escape":
            narrative_parts.append(f"{winner} rode their luck as {loser} failed to convert their chances.")
        else:
            narrative_parts.append(f"A closely contested match saw {winner} edge past {loser}.")

        if loser_data["xg"] > winner_data["xg"] + 0.3:
            narrative_parts.append(f"{loser} created better chances (xG: {loser_data['xg']:.2f} vs {winner_data['xg']:.2f}) but couldn't convert.")
        elif winner_data["xg"] > loser_data["xg"] + 0.3:
            narrative_parts.append(f"{winner}'s superior chance creation (xG: {winner_data['xg']:.2f}) was reflected in the scoreline.")

        if loser_data["total_xt"] > winner_data["total_xt"] + 0.1:
            narrative_parts.append(f"{loser} built more threatening attacks ({loser_data['total_xt']:.2f} xT) but {winner}'s efficiency proved decisive.")
        elif winner_data["total_xt"] > loser_data["total_xt"] + 0.1:
            narrative_parts.append(f"{winner}'s buildup play generated consistent danger ({winner_data['total_xt']:.2f} xT).")

        if loser_data["possession"] > winner_data["possession"] + 10:
            narrative_parts.append(f"Despite {loser}'s possession dominance ({loser_data['possession']:.0f}%), {winner} made their moments count.")
        elif winner_data["possession"] > loser_data["possession"] + 10:
            narrative_parts.append(f"{winner} controlled the tempo with {winner_data['possession']:.0f}% possession.")

        if winner_data["xg_diff"] > 0.5:
            narrative_parts.append(f"{winner} showed clinical finishing, scoring {winner_data['goals']} from {winner_data['xg']:.2f} xG.")
        if loser_data["xg_diff"] < -0.5:
            narrative_parts.append(f"{loser} will rue their wastefulness, managing only {loser_data['goals']} goals from {loser_data['xg']:.2f} xG.")

        verdict["narrative"] = " ".join(narrative_parts)
        verdict["winner"] = winner
        verdict["loser"] = loser
        verdict["score"] = f"{t1_goals}-{t2_goals}"
    else:
        # Draw — matches legacy
        verdict["verdict_type"] = "fair_draw" if abs(xg_diff) < 0.3 else "draw_flattered"
        verdict["verdict_headline"] = "Fair Result" if abs(xg_diff) < 0.3 else "Contentious Draw"
        verdict["justice_score"] = 75 if abs(xg_diff) < 0.3 else 50
        verdict["winner"] = None
        verdict["loser"] = None
        verdict["score"] = f"{t1_goals}-{t2_goals}"

        if abs(xg_diff) < 0.3:
            verdict["narrative"] = f"A fair reflection of an evenly matched contest. Both teams created similar quality chances (xG: {t1_data['xg']:.2f} vs {t2_data['xg']:.2f})."
        else:
            better_team = team1 if t1_data["xg"] > t2_data["xg"] else team2
            worse_team = team2 if better_team == team1 else team1
            verdict["narrative"] = f"{better_team} may feel hard done by after creating better chances, but {worse_team} showed resilience to earn a point."

    return verdict


# ---------------------------------------------------------------------------
# TIMELINE INSIGHTS
# ---------------------------------------------------------------------------
def generate_timeline_insights(periods, teams):
    """Matches legacy api_server.py generate_timeline_insights exactly."""
    insights = {
        "dominant_periods": [],
        "momentum_shifts": [],
        "most_attacking": {},
        "high_press_periods": [],
    }

    if len(teams) < 2 or len(periods) < 2:
        return insights

    team1, team2 = teams[0], teams[1]

    # Build dominant periods list with details for each period
    prev_leader = None
    for i, period in enumerate(periods):
        t1_data = period["teams"].get(team1, {})
        t2_data = period["teams"].get(team2, {})

        t1_passes = t1_data.get("passes", 0)
        t2_passes = t2_data.get("passes", 0)
        t1_poss = t1_data.get("possession", 50)
        t2_poss = t2_data.get("possession", 50)

        # Determine dominant team by possession
        if t1_poss > t2_poss:
            dominant = team1
            passes = t1_passes
            accuracy = t1_data.get("accuracy", 0)
        else:
            dominant = team2
            passes = t2_passes
            accuracy = t2_data.get("accuracy", 0)

        insights["dominant_periods"].append({
            "period_index": i,
            "dominant_team": dominant,
            "passes": passes,
            "accuracy": round(accuracy, 1),
            "possession": round(max(t1_poss, t2_poss), 1),
        })

        # Momentum shifts — when leader changes
        current_leader = team1 if t1_poss > t2_poss else team2
        if prev_leader and current_leader != prev_leader:
            start_min = i * 5
            insights["momentum_shifts"].append({
                "minute": start_min,
                "from_team": prev_leader,
                "to_team": current_leader,
                "description": f"{current_leader} took control from {prev_leader}",
            })
        prev_leader = current_leader

    # Most attacking periods for each team
    for team in teams:
        max_xt = 0
        max_period = None
        for i, period in enumerate(periods):
            xt = period["teams"].get(team, {}).get("xt_added", 0)
            if xt > max_xt:
                max_xt = xt
                max_period = i

        if max_period is not None:
            insights["most_attacking"][team] = {
                "start": max_period * 5,
                "end": (max_period + 1) * 5,
                "xt": round(max_xt, 4),
            }

    # High pressing periods
    for team in teams:
        for i, period in enumerate(periods):
            territory = period["teams"].get(team, {}).get("territory", {})
            attacking_territory = territory.get("attacking", 0)
            if attacking_territory > 35:
                insights["high_press_periods"].append({
                    "start": i * 5,
                    "end": (i + 1) * 5,
                    "team": team,
                    "territory": round(attacking_territory, 1),
                })

    return insights


# ---------------------------------------------------------------------------
# PLAYER DETAIL ANALYSIS
# ---------------------------------------------------------------------------
def calculate_player_detail(df, player_name, team_name=None, period=None):
    """
    Passes made/received/attempted, accuracy, progressive, under_pressure stats,
    pass_types, xT, avg_distance, recipients_detail, passers_detail, best_xt_pass.
    """
    if period is not None:
        df = df[df["period"] == period]

    # Find player's team if not provided
    if team_name is None:
        player_events = df[df["player_name"] == player_name]
        if len(player_events) > 0:
            team_name = player_events["team_name"].mode().iloc[0] if len(player_events["team_name"].mode()) > 0 else None

    # Passes made
    passes_made = df[
        (df["player_name"] == player_name) & (df["event_type"] == "Pass")
    ]
    passes_attempted = len(passes_made)
    passes_success = len(
        passes_made[
            passes_made["pass_outcome_name"].isna()
        ]
    )
    accuracy = round(passes_success / passes_attempted * 100, 1) if passes_attempted > 0 else 0

    # Passes received
    passes_received = df[
        (df["pass_recipient_name"] == player_name)
        & (df["event_type"] == "Pass")
        & (df["pass_outcome_name"].isna())
    ]

    # Progressive passes
    prog = passes_made[
        (passes_made["pass_end_location_0"].notna())
        & (passes_made["location_0"].notna())
        & (
            passes_made["pass_outcome_name"].isna()
        )
    ]
    progressive = prog[
        (prog["pass_end_location_0"] - prog["location_0"]) >= 10
    ]

    # Under pressure
    pressure = passes_made[
        (passes_made["under_pressure"] == True) | (passes_made["under_pressure"] == 1)
    ]
    pressure_success = pressure[
        pressure["pass_outcome_name"].isna()
    ]
    pressure_acc = (
        round(len(pressure_success) / len(pressure) * 100, 1)
        if len(pressure) > 0
        else 0
    )

    # Pass types
    pass_types = {}
    if "pass_type_name" in passes_made.columns:
        type_counts = passes_made["pass_type_name"].value_counts()
        for t, c in type_counts.items():
            if not pd.isna(t):
                pass_types[str(t)] = int(c)

    if "pass_height_name" in passes_made.columns:
        height_counts = passes_made["pass_height_name"].value_counts()
        for h, c in height_counts.items():
            if not pd.isna(h):
                pass_types[str(h)] = int(c)

    if "pass_body_part_name" in passes_made.columns:
        body_counts = passes_made["pass_body_part_name"].value_counts()
        for b, c in body_counts.items():
            if not pd.isna(b):
                pass_types[str(b)] = int(c)

    # xT
    xt_generated = float(passes_made["xt_added"].sum()) if "xt_added" in passes_made.columns else 0
    if pd.isna(xt_generated):
        xt_generated = 0
    xt_received = float(passes_received["xt_added"].sum()) if "xt_added" in passes_received.columns else 0
    if pd.isna(xt_received):
        xt_received = 0

    # Average distance
    valid_passes = passes_made[
        passes_made["pass_end_location_0"].notna()
        & passes_made["location_0"].notna()
        & passes_made["pass_end_location_1"].notna()
        & passes_made["location_1"].notna()
    ]
    if len(valid_passes) > 0:
        dists = np.sqrt(
            (valid_passes["pass_end_location_0"] - valid_passes["location_0"]) ** 2
            + (valid_passes["pass_end_location_1"] - valid_passes["location_1"]) ** 2
        )
        avg_distance = round(float(dists.mean()), 1)
    else:
        avg_distance = 0

    # Recipients detail
    recipients_detail = []
    if passes_attempted > 0:
        success_made = passes_made[
            passes_made["pass_outcome_name"].isna()
        ]
        rec_counts = success_made["pass_recipient_name"].value_counts()
        for rec, count in rec_counts.items():
            if not pd.isna(rec):
                recipients_detail.append(
                    {
                        "player": str(rec),
                        "nickname": get_nickname(rec),
                        "passes": int(count),
                    }
                )

    # Passers detail
    passers_detail = []
    passer_counts = passes_received["player_name"].value_counts()
    for passer, count in passer_counts.items():
        if not pd.isna(passer):
            passers_detail.append(
                {
                    "player": str(passer),
                    "nickname": get_nickname(passer),
                    "passes": int(count),
                }
            )

    # Best xT pass
    best_xt_pass = None
    if "xt_added" in passes_made.columns and len(passes_made) > 0:
        valid_xt = passes_made[passes_made["xt_added"].notna()]
        if len(valid_xt) > 0:
            best_idx = valid_xt["xt_added"].idxmax()
            best = valid_xt.loc[best_idx]
            best_xt_pass = {
                "xt_added": round(float(best["xt_added"]), 4),
                "recipient": str(best.get("pass_recipient_name", "")) if not pd.isna(best.get("pass_recipient_name", None)) else "",
                "recipient_nickname": get_nickname(best.get("pass_recipient_name", "")),
                "start_x": float(best.get("location_0", 0)) if not pd.isna(best.get("location_0", None)) else 0,
                "start_y": float(best.get("location_1", 0)) if not pd.isna(best.get("location_1", None)) else 0,
                "end_x": float(best.get("pass_end_location_0", 0)) if not pd.isna(best.get("pass_end_location_0", None)) else 0,
                "end_y": float(best.get("pass_end_location_1", 0)) if not pd.isna(best.get("pass_end_location_1", None)) else 0,
                "minute": int(best.get("minute", 0)) if not pd.isna(best.get("minute", None)) else 0,
            }

    # Average position
    player_events = df[
        (df["player_name"] == player_name)
        & (df["location_0"].notna())
        & (df["location_1"].notna())
    ]
    avg_x = round(float(player_events["location_0"].mean()), 1) if len(player_events) > 0 else 0
    avg_y = round(float(player_events["location_1"].mean()), 1) if len(player_events) > 0 else 0

    return {
        "player": player_name,
        "nickname": get_nickname(player_name),
        "team": team_name,
        "passes_attempted": passes_attempted,
        "passes_completed": passes_success,
        "passes_received": len(passes_received),
        "accuracy": accuracy,
        "progressive_passes": len(progressive),
        "under_pressure_passes": len(pressure),
        "under_pressure_accuracy": pressure_acc,
        "pass_types": pass_types,
        "xt_generated": round(xt_generated, 4),
        "xt_received": round(xt_received, 4),
        "avg_distance": avg_distance,
        "avg_x": avg_x,
        "avg_y": avg_y,
        "recipients": recipients_detail,
        "passers": passers_detail,
        "best_xt_pass": best_xt_pass,
    }


# ---------------------------------------------------------------------------
# GOAL ANALYSIS
# ---------------------------------------------------------------------------
def calculate_goals_with_buildup(df, match_date):
    """Find goals, trace back 15 Pass/Carry events by same team, calculate buildup xT.
    Matches legacy api_server.py /goals/{match_date} endpoint."""
    goals_df = df[(df["event_type"] == "Shot") & (df["shot_outcome_name"] == "Goal")]

    goals = []
    for _, goal in goals_df.iterrows():
        team = goal["team_name"]
        minute = int(goal["minute"]) if not pd.isna(goal.get("minute", None)) else 0
        scorer = goal.get("player_name", "Unknown")
        xg = float(goal.get("shot_statsbomb_xg", 0)) if not pd.isna(goal.get("shot_statsbomb_xg", None)) else 0

        # Legacy: filter to only Pass and Carry BEFORE .tail(15)
        goal_idx = goal.name
        team_events_before = df[
            (df.index < goal_idx)
            & (df["team_name"] == team)
            & (df["event_type"].isin(["Pass", "Carry"]))
        ].tail(15)

        buildup = []
        buildup_xt = 0.0

        for _, event in team_events_before.iterrows():
            evt_type = str(event.get("event_type", ""))
            player_name = str(event.get("player_name", "Unknown"))

            x = float(event.get("location_0", 0)) if not pd.isna(event.get("location_0", None)) else 0
            y = float(event.get("location_1", 0)) if not pd.isna(event.get("location_1", None)) else 0

            start_xt = get_buildup_xt(x, y)

            end_x = 0
            end_y = 0
            if evt_type == "Pass":
                end_x = float(event.get("pass_end_location_0", 0)) if not pd.isna(event.get("pass_end_location_0", None)) else 0
                end_y = float(event.get("pass_end_location_1", 0)) if not pd.isna(event.get("pass_end_location_1", None)) else 0
            elif evt_type == "Carry":
                end_x = float(event.get("carry_end_location_0", 0)) if not pd.isna(event.get("carry_end_location_0", None)) else 0
                end_y = float(event.get("carry_end_location_1", 0)) if not pd.isna(event.get("carry_end_location_1", None)) else 0

            end_xt = get_buildup_xt(end_x, end_y)
            xt_added = end_xt - start_xt

            # Legacy: only sum positive xT contributions
            if xt_added > 0:
                buildup_xt += xt_added

            # Legacy fields: recipient and pass_type for passes
            entry = {
                "event_type": evt_type,
                "player": player_name,
                "nickname": get_nickname(player_name),
                "x": round(x, 1),
                "y": round(y, 1),
                "end_x": round(end_x, 1),
                "end_y": round(end_y, 1),
                "xt_added": round(xt_added, 4),
                "minute": int(event.get("minute", 0)) if not pd.isna(event.get("minute", None)) else 0,
            }

            if evt_type == "Pass":
                recipient = str(event.get("pass_recipient_name", ""))
                pass_type = str(event.get("pass_type_name", ""))
                entry["recipient"] = recipient if recipient and recipient != "nan" else None
                entry["pass_type"] = pass_type if pass_type and pass_type != "nan" else None

            buildup.append(entry)

        # Count positive xT events (legacy: buildup_events)
        buildup_events_count = sum(1 for b in buildup if b["xt_added"] > 0)

        goals.append(
            {
                "index": len(goals),
                "scorer": str(scorer),
                "scorer_nickname": get_nickname(scorer),
                "team": str(team),
                "minute": minute,
                "xg": round(xg, 4),
                "x": float(goal.get("location_0", 0)) if not pd.isna(goal.get("location_0", None)) else 0,
                "y": float(goal.get("location_1", 0)) if not pd.isna(goal.get("location_1", None)) else 0,
                "buildup_xt": round(buildup_xt, 4),
                "buildup_events": buildup_events_count,
                "buildup_sequence": buildup,
            }
        )

    return goals


# ---------------------------------------------------------------------------
# TIMELINE ANALYSIS (5-minute periods)
# ---------------------------------------------------------------------------
def calculate_timeline(df, match_date):
    """5-minute periods — matches legacy api_server.py /timeline-analysis endpoint."""
    teams = df["team_name"].dropna().unique().tolist()
    max_minute = int(df["minute"].max()) if pd.notna(df["minute"].max()) else 90

    periods = []

    for start_min in range(0, max_minute + 1, 5):
        end_min = min(start_min + 5, max_minute + 1)
        period_df = df[(df["minute"] >= start_min) & (df["minute"] < end_min)]

        period_data = {
            "start": start_min,
            "end": end_min,
            "label": f"{start_min}'-{end_min}'",
            "teams": {},
        }

        for team in teams:
            # Legacy: successful = isna() only
            team_passes = period_df[
                (period_df["team_name"] == team)
                & (period_df["event_type"] == "Pass")
                & (period_df["pass_outcome_name"].isna())
            ]

            total_passes = len(period_df[
                (period_df["team_name"] == team)
                & (period_df["event_type"] == "Pass")
            ])

            successful = len(team_passes)
            accuracy = round(successful / total_passes * 100, 1) if total_passes > 0 else 0

            # xT — legacy uses successful passes and field name xt_added
            xt_added = 0
            if "xt_added" in team_passes.columns:
                xt_val = team_passes["xt_added"].sum()
                xt_added = round(float(xt_val), 3) if not pd.isna(xt_val) else 0

            # Territory — legacy: {defensive, middle, attacking} percentages
            territory = {"defensive": 0, "middle": 0, "attacking": 0}
            for _, p in team_passes.iterrows():
                x = p.get("location_0", 0)
                if pd.notna(x):
                    if x < 40:
                        territory["defensive"] += 1
                    elif x < 80:
                        territory["middle"] += 1
                    else:
                        territory["attacking"] += 1

            total_territory = sum(territory.values()) or 1
            territory = {k: round(v / total_territory * 100, 1) for k, v in territory.items()}

            # Top passers — legacy returns dict {player: count}
            top_passers = {}
            if len(team_passes) > 0:
                passer_counts = team_passes["player_name"].value_counts().head(3)
                top_passers = {str(k): int(v) for k, v in passer_counts.items()}

            period_data["teams"][team] = {
                "passes": successful,
                "total_passes": total_passes,
                "accuracy": accuracy,
                "xt_added": xt_added,
                "territory": territory,
                "top_passers": top_passers,
            }

        # Possession — legacy: calculated from successful pass share
        total_passes_period = sum(t.get("passes", 0) for t in period_data["teams"].values())
        if total_passes_period > 0:
            for team in period_data["teams"]:
                period_data["teams"][team]["possession"] = round(
                    period_data["teams"][team]["passes"] / total_passes_period * 100, 1
                )
        else:
            for team in period_data["teams"]:
                period_data["teams"][team]["possession"] = 0

        periods.append(period_data)

    # Generate insights
    insights = generate_timeline_insights(periods, teams)

    # Verdict
    verdict = calculate_match_verdict(df, teams, periods)

    return {
        "match_date": match_date,
        "max_minute": max_minute,
        "teams": teams,
        "periods": periods,
        "insights": insights,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# COMMAND HANDLERS
# ---------------------------------------------------------------------------
def handle_health(cmd):
    match_list = []
    for match_date, mdf in MATCH_DATA.items():
        teams = mdf["team_name"].dropna().unique().tolist()
        match_list.append({"date": match_date, "teams": teams})
    return {
        "status": "ok",
        "matches_loaded": len(MATCH_DATA),
        "matches": match_list,
    }


def _parse_competition(sheet_name):
    """Extract competition name from sheet name."""
    s = sheet_name
    if "Euro" in s:
        return "UEFA Euro 2024"
    elif "World_Cup_2022" in s:
        return "FIFA World Cup 2022"
    elif "Copa_America" in s:
        return "Copa America 2024"
    elif "Women" in s or "women" in s:
        return "FIFA Women's World Cup 2023"
    elif "AFCON" in s:
        return "AFCON 2023"
    elif s in ("2018-05-26", "2019-06-01"):
        return "UEFA Champions League Final"
    return "Other"


def handle_matches(cmd):
    matches = []
    for match_date, mdf in MATCH_DATA.items():
        teams = mdf["team_name"].dropna().unique().tolist()
        home = str(mdf["home_team"].dropna().iloc[0]) if "home_team" in mdf.columns and len(mdf["home_team"].dropna()) > 0 else (teams[0] if teams else "")
        away = str(mdf["away_team"].dropna().iloc[0]) if "away_team" in mdf.columns and len(mdf["away_team"].dropna()) > 0 else (teams[1] if len(teams) > 1 else "")
        competition = _parse_competition(match_date)
        # Extract just the date part for display
        date_part = match_date.split("_")[0] if "_" in match_date else match_date
        matches.append(
            {
                "date": match_date,
                "date_display": date_part,
                "home_team": home,
                "away_team": away,
                "competition": competition,
                "events": len(mdf),
                "columns": list(mdf.columns),
            }
        )
    return {"matches": matches}


def handle_teams(cmd):
    match_date = cmd.get("match_date", "")
    if match_date not in MATCH_DATA:
        return {"error": f"Match {match_date} not found"}
    mdf = MATCH_DATA[match_date]
    teams = mdf["team_name"].dropna().unique().tolist()
    return {"teams": teams, "match_date": match_date}


def handle_all_teams(cmd):
    """Every distinct team name across ALL loaded matches — powers an
    opponent picker that isn't tied to a single match's dropdown, so you
    can pick a team and see their profile across every match they're in."""
    teams = set()
    for mdf in MATCH_DATA.values():
        teams.update(mdf["team_name"].dropna().unique().tolist())
    return {"teams": sorted(teams)}


def handle_network(cmd):
    match_date = cmd.get("match_date", "")
    team = cmd.get("team", "")
    period = cmd.get("period", None)
    minute_start = cmd.get("minute_start", 0)
    minute_end = cmd.get("minute_end", 120)

    if match_date not in MATCH_DATA:
        return {"error": f"Match {match_date} not found"}

    mdf = MATCH_DATA[match_date].copy()

    # Filter by period
    if period is not None:
        mdf = mdf[mdf["period"] == period]

    # Filter by minutes
    mdf = mdf[(mdf["minute"] >= minute_start) & (mdf["minute"] <= minute_end)]

    if not team:
        teams = mdf["team_name"].dropna().unique().tolist()
        team = teams[0] if teams else ""

    network = calculate_network_metrics(mdf, team)
    if network is None:
        return {"error": "No pass data for team"}

    weakest = calculate_weakest_link(mdf, team, network)
    metrics = network.get("metrics", {})

    # Find hub nickname
    hub_name = metrics.get("hub_player", "")
    hub_nickname = get_nickname(hub_name) if hub_name else None

    return {
        "team": team,
        "match_date": match_date,
        "period": period,
        "minute_start": minute_start,
        "minute_end": minute_end,
        "players": network["players"],
        "edges": network["edges"],
        "metrics": {
            "num_players": metrics.get("num_players", 0),
            "num_edges": metrics.get("num_connections", 0),
            "density": metrics.get("network_density", 0),
            "hub": hub_nickname,
            "hub_involvement": metrics.get("hub_involvement", 0),
        },
        "weakest_link": weakest,
    }


def handle_insights(cmd):
    match_date = cmd.get("match_date", "")
    team = cmd.get("team", "")
    period = cmd.get("period", None)

    if match_date not in MATCH_DATA:
        return {"error": f"Match {match_date} not found"}

    mdf = MATCH_DATA[match_date].copy()
    if period is not None:
        mdf = mdf[mdf["period"] == period]

    if not team:
        teams = mdf["team_name"].dropna().unique().tolist()
        team = teams[0] if teams else ""

    insights = calculate_advanced_insights(mdf, team)
    return {"team": team, "match_date": match_date, "period": period, **insights}


def handle_compare(cmd):
    match_date = cmd.get("match_date", "")
    period = cmd.get("period", None)

    if match_date not in MATCH_DATA:
        return {"error": f"Match {match_date} not found"}

    mdf = MATCH_DATA[match_date].copy()
    if period is not None:
        mdf = mdf[mdf["period"] == period]

    teams = mdf["team_name"].dropna().unique().tolist()
    comparison = {}

    for team in teams:
        network = calculate_network_metrics(mdf, team)
        weakest = calculate_weakest_link(mdf, team, network)

        all_passes = mdf[(mdf["team_name"] == team) & (mdf["event_type"] == "Pass")]
        success = all_passes[
            all_passes["pass_outcome_name"].isna()
        ]
        accuracy = round(len(success) / len(all_passes) * 100, 1) if len(all_passes) > 0 else 0

        xt = float(mdf[mdf["team_name"] == team]["xt_added"].sum()) if "xt_added" in mdf.columns else 0
        if pd.isna(xt):
            xt = 0

        prog = get_progressive_passes(mdf, team)
        ppda = calculate_ppda(mdf, team)
        field_tilt = calculate_field_tilt(mdf, team)
        shape = calculate_team_shape(mdf, team)
        grund = calculate_thomas_grund_centrality(mdf, team, network)
        rate = calculate_passing_rate(mdf, team)
        if rate is None:
            rate = {"passes_per_minute": 0, "rating": "N/A", "total_passes": 0}

        nm = network.get("metrics", {}) if network else {}
        comparison[team] = {
            "network": {
                "num_players": nm.get("num_players", 0),
                "num_edges": nm.get("num_connections", 0),
                "density": nm.get("network_density", 0),
                "hub": get_nickname(nm.get("hub_player", "")) if nm.get("hub_player") else None,
                "hub_involvement": nm.get("hub_involvement", 0),
            },
            "passes": len(all_passes),
            "accuracy": accuracy,
            "xt": round(xt, 4),
            "progressive_passes": len(prog),
            "ppda": ppda,
            "field_tilt": field_tilt,
            "team_shape": shape,
            "centrality": {
                "index": grund["centrality_percentage"] if grund else 0,
                "style": grund["style"] if grund else "unknown",
            },
            "passing_rate": rate,
            "weakest_link": weakest.get("weakest_link") if weakest else None,
        }

    return {"match_date": match_date, "period": period, "teams": comparison}


def handle_timeline(cmd):
    match_date = cmd.get("match_date", "")

    if match_date not in MATCH_DATA:
        return {"error": f"Match {match_date} not found"}

    mdf = MATCH_DATA[match_date]
    return calculate_timeline(mdf, match_date)


def handle_goals(cmd):
    match_date = cmd.get("match_date", "")

    if match_date not in MATCH_DATA:
        return {"error": f"Match {match_date} not found"}

    mdf = MATCH_DATA[match_date]
    goals = calculate_goals_with_buildup(mdf, match_date)
    return {"match_date": match_date, "goals": goals, "total": len(goals)}


def handle_tactical(cmd):
    match_date = cmd.get("match_date", "")
    team = cmd.get("team", "")
    period = cmd.get("period", None)

    if match_date not in MATCH_DATA:
        return {"error": f"Match {match_date} not found"}

    mdf = MATCH_DATA[match_date].copy()
    if period is not None:
        mdf = mdf[mdf["period"] == period]

    if not team:
        teams = mdf["team_name"].dropna().unique().tolist()
        team = teams[0] if teams else ""

    network = calculate_network_metrics(mdf, team)
    grund = calculate_thomas_grund_centrality(mdf, team, network)
    rate = calculate_passing_rate(mdf, team)

    if rate is None:
        rate = {"passes_per_minute": 0, "rating": "N/A", "total_passes": 0, "estimated_possession_minutes": 0, "possession_percentage": 0}

    # Add hub betweenness from network data
    if grund and network:
        hub_info = grund.get("hub_player", {})
        hub_name = hub_info.get("name", "") if isinstance(hub_info, dict) else ""
        players = network.get("players", [])
        for p in players:
            if p.get("name") == hub_name:
                grund["hub_betweenness"] = p.get("betweenness_centrality", 0)
                break

    # Tactical narrative
    if grund:
        hub_info = grund.get("hub_player", {})
        hub_nickname = hub_info.get("nickname", "") if isinstance(hub_info, dict) else ""
        hub_involvement = hub_info.get("total_involvement", 0) if isinstance(hub_info, dict) else 0
        narrative = (
            f"{team}'s passing network is {grund['style']} "
            f"(centrality index: {grund['centrality_percentage']}%). "
            f"The team averages {rate['passes_per_minute']} passes per minute "
            f"of possession ({rate['rating']}). "
        )
        if hub_nickname:
            narrative += (
                f"The orchestrator is {hub_nickname} with "
                f"{hub_involvement} involvements."
            )
    else:
        narrative = f"Insufficient data for {team}'s tactical analysis."

    return {
        "team": team,
        "match_date": match_date,
        "period": period,
        "centrality": grund,
        "passing_rate": rate,
        "narrative": narrative,
    }


def handle_tactical_map(cmd):
    match_date = cmd.get("match_date", "")
    team = cmd.get("team", "")

    if match_date not in MATCH_DATA:
        return {"error": f"Match {match_date} not found"}

    mdf = MATCH_DATA[match_date]

    if not team:
        teams = mdf["team_name"].dropna().unique().tolist()
        team = teams[0] if teams else ""

    result = calculate_tactical_map_25_zones(mdf, team)
    if result is None:
        return {"team": team, "match_date": match_date, "zones": [], "total_passes": 0, "max_zone_count": 0}

    # Convert zones dict to list for React component
    zones_list = list(result["zones"].values()) if isinstance(result["zones"], dict) else result["zones"]

    return {
        "team": team,
        "match_date": match_date,
        "zones": zones_list,
        "total_passes": result["total_passes"],
        "max_zone_count": result["max_zone_count"],
    }


def handle_zone_directions(cmd):
    match_date = cmd.get("match_date", "")
    team = cmd.get("team", "")

    if match_date not in MATCH_DATA:
        return {"error": f"Match {match_date} not found"}

    mdf = MATCH_DATA[match_date]

    if not team:
        teams = mdf["team_name"].dropna().unique().tolist()
        team = teams[0] if teams else ""

    result = calculate_zone_pass_directions(mdf, team)
    if result is None:
        return {"team": team, "match_date": match_date, "zones": [], "total_passes": 0}

    # Convert zones dict to list for React component
    zones_list = list(result["zones"].values()) if isinstance(result["zones"], dict) else result["zones"]
    return {"team": team, "match_date": match_date, "zones": zones_list, "total_passes": result["total_passes"]}


def handle_zone_connections(cmd):
    match_date = cmd.get("match_date", "")
    team = cmd.get("team", "")
    min_passes = cmd.get("min_passes", 1)

    if match_date not in MATCH_DATA:
        return {"error": f"Match {match_date} not found"}

    mdf = MATCH_DATA[match_date]

    if not team:
        teams = mdf["team_name"].dropna().unique().tolist()
        team = teams[0] if teams else ""

    result = calculate_zone_connections(mdf, team, min_passes)
    if result is None:
        return {"team": team, "match_date": match_date, "connections": [], "total_connections": 0}

    return {
        "team": team,
        "match_date": match_date,
        "min_passes": min_passes,
        **result,
    }


def handle_shots(cmd):
    match_date = cmd.get("match_date", "")
    team = cmd.get("team", "")

    if match_date not in MATCH_DATA:
        return {"error": f"Match {match_date} not found"}

    mdf = MATCH_DATA[match_date]

    if not team:
        teams = mdf["team_name"].dropna().unique().tolist()
        team = teams[0] if teams else ""

    return {
        "team": team,
        "match_date": match_date,
        **calculate_shot_map(mdf, team),
    }


def handle_player(cmd):
    match_date = cmd.get("match_date", "")
    player_name = cmd.get("player_name", "")
    period = cmd.get("period", None)

    if match_date not in MATCH_DATA:
        return {"error": f"Match {match_date} not found"}

    mdf = MATCH_DATA[match_date]
    result = calculate_player_detail(mdf, player_name, period=period)
    return {"match_date": match_date, **result}


def handle_opponent_profile(cmd):
    """Opponent scouting profile: this team's tactical identity averaged
    across every match they appear in, with a per-match trend and a short
    list of plain-language takeaways. This is the multi-match counterpart
    to handle_tactical/handle_compare, which are both single-match."""
    team = cmd.get("team", "")
    if not team:
        return {"error": "team is required"}

    profile = calculate_opponent_profile(team)
    if profile is None:
        return {"error": f"No matches found for team '{team}'"}
    return profile


def handle_team_players(cmd):
    """Every player who appears for a given team across ALL loaded
    matches — powers a player picker scoped to the team just selected in
    Opponent Scout, rather than dumping every player from every match."""
    team = cmd.get("team", "")
    if not team:
        return {"error": "team is required"}

    players = set()
    for mdf in MATCH_DATA.values():
        if team not in mdf["team_name"].dropna().unique().tolist():
            continue
        team_events = mdf[mdf["team_name"] == team]
        players.update(team_events["player_name"].dropna().unique().tolist())

    result = sorted(
        [{"name": p, "nickname": get_nickname(p)} for p in players],
        key=lambda x: x["nickname"],
    )
    return {"team": team, "players": result}


def handle_player_profile(cmd):
    """Player scouting profile: this player's performance averaged across
    every match they appear in, with a per-match trend and takeaways —
    the player-side counterpart to handle_opponent_profile."""
    player_name = cmd.get("player_name", "")
    if not player_name:
        return {"error": "player_name is required"}

    profile = calculate_player_profile(player_name)
    if profile is None:
        return {"error": f"No matches found for player '{player_name}'"}
    return profile


# ---------------------------------------------------------------------------
# COMMAND ROUTER
# ---------------------------------------------------------------------------
def handle_upload_csv(cmd):
    """Register a user-uploaded match CSV under a chosen key.
    Schema must match the StatsBomb event format the engine expects."""
    csv_path = cmd.get("csv_path", "")
    match_name = (cmd.get("match_name") or "").strip()
    if not csv_path or not os.path.exists(csv_path):
        return {"error": f"CSV not found at {csv_path}"}
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        return {"error": f"Failed to read CSV: {e}"}

    required = {"team_name", "event_type", "minute"}
    missing = required - set(df.columns)
    if missing:
        return {"error": f"CSV is missing required columns: {sorted(missing)}"}

    # xT column is optional; if absent, fill with 0 so timeline/verdict don't crash
    if "xt_added" not in df.columns:
        df["xt_added"] = 0.0

    key = match_name or f"uploaded_{int(time.time())}"
    # Ensure uniqueness — if the key already exists, append a counter
    base_key = key
    i = 1
    while key in MATCH_DATA:
        i += 1
        key = f"{base_key}_{i}"

    MATCH_DATA[key] = df
    teams = df["team_name"].dropna().unique().tolist()
    return {
        "status": "ok",
        "match_date": key,
        "teams": teams,
        "events": len(df),
        "matches_loaded": len(MATCH_DATA),
    }


COMMAND_HANDLERS = {
    "health": handle_health,
    "matches": handle_matches,
    "teams": handle_teams,
    "all_teams": handle_all_teams,
    "network": handle_network,
    "insights": handle_insights,
    "compare": handle_compare,
    "timeline": handle_timeline,
    "goals": handle_goals,
    "tactical": handle_tactical,
    "tactical_map": handle_tactical_map,
    "zone_directions": handle_zone_directions,
    "zone_connections": handle_zone_connections,
    "shots": handle_shots,
    "player": handle_player,
    "opponent_profile": handle_opponent_profile,
    "team_players": handle_team_players,
    "player_profile": handle_player_profile,
    "upload_csv": handle_upload_csv,
}


def handle_command(cmd):
    command = cmd.get("command", "")
    handler = COMMAND_HANDLERS.get(command)
    if handler:
        return handler(cmd)
    return {"error": f"Unknown command: {command}"}


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    loaded = load_data()
    print(f"Passing-networks server ready: {loaded} matches loaded", flush=True)

    # Signal ready on real stdout (JSON format matching what passing-predict.ts expects)
    _real_stdout.write(
        json.dumps({"status": "ready", "matches_loaded": loaded}) + "\n"
    )
    _real_stdout.flush()

    # Process requests in a loop
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        sys.stdout = sys.stderr

        try:
            cmd = json.loads(line)
            result = handle_command(cmd)

            sys.stdout = _real_stdout
            _real_stdout.write(json.dumps(result, default=str) + "\n")
            _real_stdout.flush()
        except Exception as e:
            sys.stdout = _real_stdout
            tb = traceback.format_exc()
            print(f"Error processing command: {tb}", file=sys.stderr, flush=True)
            _real_stdout.write(json.dumps({"error": str(e)}) + "\n")
            _real_stdout.flush()