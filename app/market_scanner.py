# ============================================================
# MARKET SCANNER – PRODUCCIÓN REAL
# ============================================================

from app.hyperliquid_client import make_request
from app.config import SCANNER_DEPTH

def get_all_24h_stats():
    r = make_request("/info", {"type": "metaAndAssetCtxs"})
    if not r or len(r) < 2:
        return {}

    meta, ctxs = r
    universe = meta.get("universe", [])
    stats = {}

    for i, ctx in enumerate(ctxs):
        symbol = universe[i]["name"].upper()
        price = float(ctx["markPx"])
        volume = float(ctx["dayNtlVlm"])
        oi = float(ctx["openInterest"])

        if price < 0.01 or volume < 200_000 or oi < 500_000:
            continue

        stats[symbol] = ctx

    return stats

def get_best_symbol(exclude: set | None = None):
    exclude = exclude or set()
    stats = get_all_24h_stats()

    ranked = sorted(
        stats.keys(),
        key=lambda s: stats[s]["dayNtlVlm"] + stats[s]["openInterest"],
        reverse=True
    )

    return ranked[0] if ranked else None
