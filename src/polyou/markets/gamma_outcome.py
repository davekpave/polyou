import httpx

GAMMA_BASE = "https://gamma-api.polymarket.com"

async def fetch_resolved_outcome(token_id: str) -> str | None:
    """
    Fetch the resolved outcome for a given token_id from the Gamma API.
    Returns the outcome string (e.g., "up", "down", "yes", "no") or None if unresolved.
    """
    url = f"{GAMMA_BASE}/tokens/{token_id}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
            data = resp.json()
            # Gamma returns { ... , "resolvedOutcome": "up"/"down"/None, ... }
            return data.get("resolvedOutcome")
    except Exception:
        return None
