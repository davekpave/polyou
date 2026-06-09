import logging
import json
import os
from typing import Dict, Any, Optional

from polyou.utils.telegram_notifier import send_telegram_message

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

def is_retriable_order_error(e: Exception) -> bool:
    err = str(e).lower()
    if "balance" in err or "allowance" in err or "exceeds" in err or "sufficient" in err:
        return False
    # R:R cap breach — book moved above our limit; retrying is futile.
    if "r:r cap" in err:
        return False
    return True

from py_clob_client_v2 import ClobClient
from py_clob_client_v2.clob_types import OrderArgs, BalanceAllowanceParams, AssetType, OrderType, ApiCreds
from py_clob_client_v2.order_builder.builder import ROUNDING_CONFIG
from py_clob_client_v2.clob_types import RoundConfig
from eth_account import Account

# --- SDK MONKEY PATCH FOR 400 PRECISION ERROR ---
# The Polymarket SDK calculates Maker Amounts as floating point numbers (e.g. 3.0 * 0.05 = 0.15000000000000002)
# By default, it sets the tick_size '0.01' amount limit to 4.
# However, the CLOB strictly enforces a max limit of 2 decimal places for USDC maker amounts.
if "0.01" in ROUNDING_CONFIG:
    ROUNDING_CONFIG["0.01"] = RoundConfig(
        price=2,
        size=2,
        amount=4
    )

logger = logging.getLogger("execution_client")

EXECUTION_STATE_FILE = "execution_state.json"
ACTIVE_POSITIONS_FILE = "active_positions.json"
CLOB_CREDS_FILE = "clob_creds.json"


class ExecutionClient:
    def __init__(self, *, api_key: str = None, base_url: str, paper_trading: bool = False):
        # ----------------------------------
        # WALLET SIGNER (REQUIRED)
        # ----------------------------------
        private_key = os.getenv("POLY_PRIVATE_KEY")
        if not private_key:
            raise ValueError("POLY_PRIVATE_KEY missing")

        # ----------------------------------
        # SIGNER IDENTITY
        # ----------------------------------
        self.account = Account.from_key(private_key)
        self.address = self.account.address
        
        # Determine the funder address (Proxy Address if provided, else EOA)
        self.proxy_address = os.getenv("POLYMARKET_PROXY_ADDRESS")
        self.funder = self.proxy_address if self.proxy_address else self.address

        # ----------------------------------
        # CLIENT (UPDATED FOR PROXY WALLET)
        # ----------------------------------
        # When using proxy wallet, signature_type must be 2 (EOA is 0, POLYGON_GATELSSS is 1, POLYMARKET_GNOSIS_SAFE is 2)
        signature_type = 2 if self.proxy_address else 0
        
        self.client = ClobClient(
            host="https://clob.polymarket.com",
            key=private_key,
            chain_id=137,
            funder=self.funder,
            signature_type=signature_type,
        )

        # ----------------------------------
        # ✅ CLOB API CREDS (cache-first; survives Cloudflare 403 on /auth/api-key)
        # ----------------------------------
        creds = self._load_or_derive_creds()
        self.client.set_api_creds(creds)

        logger.info("CLOB API creds initialized for Proxy Wallet")

        logger.info("Execution signer address: %s", self.address)
        
        # ----------------------------------
        # SET TOKEN ALLOWANCES
        # ----------------------------------
        try:
            # Set allowance for USDC collateral to enable trading
            # This allows the CLOB Exchange to spend your USDC for trades
            logger.info("Setting USDC allowance for CLOB Exchange...")
            
            collateral_params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            self.client.update_balance_allowance(params=collateral_params)
            
            logger.info("✅ USDC allowance set successfully")
        except Exception as e:
            logger.warning("Could not set USDC allowance (may already be set): %s", str(e))

        # ----------------------------------
        # DUPLICATE PROTECTION & POSITIONS
        # ----------------------------------
        self._executed_orders = set()
        self.active_positions = {}
        self._load_state()
        self.paper_trading = paper_trading

    def _load_or_derive_creds(self) -> ApiCreds:
        """Load CLOB API creds from disk if cached for this signer; otherwise
        derive from the network (with retry) and cache for next restart.
        Cloudflare frequently 403s /auth/api-key — caching makes restarts
        immune once we have one good run."""
        # 1) Try cache
        if os.path.exists(CLOB_CREDS_FILE):
            try:
                with open(CLOB_CREDS_FILE, "r") as f:
                    data = json.load(f)
                if data.get("signer") == self.address and data.get("funder") == self.funder:
                    logger.info("Loaded CLOB API creds from cache")
                    return ApiCreds(
                        api_key=data["api_key"],
                        api_secret=data["api_secret"],
                        api_passphrase=data["api_passphrase"],
                    )
                else:
                    logger.warning("Cached CLOB creds belong to a different signer/funder; re-deriving")
            except Exception as e:
                logger.warning("Failed to read cached CLOB creds (%s); re-deriving", e)

        # 2) Derive from network with retry (Cloudflare often 403s briefly)
        last_err: Optional[Exception] = None
        for attempt in range(1, 5):
            try:
                creds = self.client.create_or_derive_api_key()
                # 3) Cache for next restart
                try:
                    with open(CLOB_CREDS_FILE, "w") as f:
                        json.dump({
                            "signer": self.address,
                            "funder": self.funder,
                            "api_key": creds.api_key,
                            "api_secret": creds.api_secret,
                            "api_passphrase": creds.api_passphrase,
                        }, f)
                    logger.info("Derived CLOB API creds from network and cached to %s", CLOB_CREDS_FILE)
                except Exception as e:
                    logger.warning("Could not cache CLOB creds: %s", e)
                return creds
            except Exception as e:
                last_err = e
                wait_s = 5 * attempt
                logger.warning("create_or_derive_api_key attempt %d/4 failed (%s); retrying in %ds",
                               attempt, type(e).__name__, wait_s)
                import time
                time.sleep(wait_s)
        raise RuntimeError(f"Failed to obtain CLOB API creds after 4 attempts: {last_err}")

    def _build_order_id(self, contract_slug: str, side: str, window_end_ts: int) -> str:
        return f"{contract_slug}:{side}:{window_end_ts}"

    def _load_state(self):
        try:
            if os.path.exists(EXECUTION_STATE_FILE):
                with open(EXECUTION_STATE_FILE, "r") as f:
                    data = json.load(f)
                    self._executed_orders = set(data)
                    logger.info(
                        "Loaded execution state | %d orders",
                        len(self._executed_orders),
                    )
            if os.path.exists(ACTIVE_POSITIONS_FILE):
                with open(ACTIVE_POSITIONS_FILE, "r") as f:
                    self.active_positions = json.load(f)
                    logger.info(
                        "Loaded active positions | %d positions",
                        len(self.active_positions),
                    )
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.exception("Failed to load execution state or active positions: %s", e)

    def _persist_state(self):
        try:
            with open(EXECUTION_STATE_FILE, "w") as f:
                json.dump(list(self._executed_orders), f)
            with open(ACTIVE_POSITIONS_FILE, "w") as f:
                json.dump(self.active_positions, f)
        except (OSError, TypeError) as e:
            logger.exception("Failed to persist execution state or active positions: %s", e)

    # ----------------------------------
    # REAL ORDER EXECUTION
    # ----------------------------------
    async def _fetch_live_ask(self, token_id: str) -> Optional[float]:
        """Fetch the current best ask from CLOB right before order submission.
        Eliminates staleness between signal snapshot and order post."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(
                    "https://clob.polymarket.com/book",
                    params={"token_id": token_id},
                )
                if resp.status_code == 200:
                    asks = resp.json().get("asks", [])
                    if asks:
                        return min(float(a["price"]) for a in asks if float(a["price"]) > 0)
        except Exception as e:
            logger.warning("Live ask refresh failed: %s", str(e))
        return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=5),
        retry=retry_if_exception(is_retriable_order_error)
    )
    async def _post_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            # Re-fetch the live ask immediately before signing so each retry
            # attempt uses a fresh price. This is the critical fix for FAK kills
            # caused by book movement between signal snapshot and submission.
            live_ask = await self._fetch_live_ask(payload["market"])
            if live_ask is not None:
                # 0.85 cap = 85% breakeven W/R. Entries above 0.85 have
                # poor R:R (risking 85c to win 15c) and are excluded.
                if live_ask > 0.85:
                    logger.warning(
                        "Skip order | live_ask=%.3f above 0.85 cap (snapshot=%.2f)",
                        live_ask, payload["price"],
                    )
                    raise ValueError(
                        f"live_ask {live_ask:.3f} exceeds 0.85 cap — sufficient liquidity unavailable"
                    )

                # +5¢ to cross the spread reliably; 0.85 cap
                refreshed_price = min(0.85, round(live_ask + 0.05, 2))
                if abs(refreshed_price - payload["price"]) >= 0.01:
                    logger.info(
                        "Refreshed entry price | snapshot=%.2f live_ask=%.2f new_limit=%.2f",
                        payload["price"], live_ask, refreshed_price,
                    )
                payload = {**payload, "price": refreshed_price}

            order_args = OrderArgs(
                token_id=payload["market"],
                side=payload["side"],
                price=payload["price"],
                size=payload["size"],
            )

            signed_order = self.client.create_order(order_args)
            
            # Retrieve order_type, defaulting to FOK to guarantee atomic fills
            order_type = payload.get("order_type", OrderType.FOK)
            response = self.client.post_order(signed_order, order_type=order_type)

            return response

        except Exception as e:
            logger.error("Execution error | %s", str(e))
            raise

    async def test_order_capability(self) -> bool:
        logger.debug("Execution test skipped (CLOB requires real token_id)")
        return True

    async def _fetch_order_fill_size(self, real_order_id: str) -> tuple[Optional[float], Optional[str]]:
        """Verify an order's filled size with one retry.

        Returns (filled_size, status). Either may be None if the API never
        gave us usable data after the retry; callers must treat None
        explicitly (do NOT silently fall back to assumed full size).
        """
        import asyncio

        for attempt in (1, 2):
            try:
                check_resp = self.client.get_order(real_order_id)
                if check_resp is None:
                    raise ValueError("get_order returned None")
                filled_raw = (
                    check_resp.get("size_matched")
                    or check_resp.get("filled_size")
                    or check_resp.get("sizeMached")
                )
                status = check_resp.get("status") or check_resp.get("state")
                filled_size = float(filled_raw) if filled_raw is not None else None
                return filled_size, status
            except Exception as e:
                logger.warning(
                    "Fill verification attempt %d failed | order=%s err=%s",
                    attempt, real_order_id, str(e),
                )
                if attempt == 1:
                    await asyncio.sleep(0.5)
        return None, None

    # ----------------------------------
    # EXECUTION ENTRY (UNCHANGED SAFETY)
    # ----------------------------------
    async def execute_trade(
        self,
        *,
        symbol: str,
        contract_slug: str,
        token_id: str,
        side: str,
        price: float,
        size: float,
        window_end_ts: int,
    ) -> Optional[Dict[str, Any]]:
        if self.paper_trading:
            logger.info("[PAPER] Simulating trade | symbol=%s side=%s price=%.4f size=%.4f window_end_ts=%s", symbol, side, price, size, window_end_ts)
            order_id = self._build_order_id(contract_slug, side, window_end_ts)
            self._executed_orders.add(order_id)
            self.active_positions[token_id] = {
                "token_id": token_id,
                "symbol": symbol,
                "side": side,
                "contract_slug": contract_slug,
                "entry_price": price,
                "size": size,
                "window_end_ts": window_end_ts,
                "real_order_id": f"PAPER-{order_id}",
            }
            self._persist_state()
            logger.info("[PAPER] EXECUTED | %s | side=%s price=%.4f size=%.4f notional=%.2f status=filled", contract_slug, side, price, size, price * size)
            return {"id": f"PAPER-{order_id}", "status": "filled", "price": price, "size": size}

        order_id = self._build_order_id(contract_slug, side, window_end_ts)

        if order_id in self._executed_orders:
            logger.warning("Duplicate trade prevented | %s", order_id)
            return None

        TARGET_NOTIONAL = size
        SAFETY_BUFFER = 0.98

        if price <= 0:
            logger.error("Invalid price for sizing | %s", price)
            return None

        effective_notional = TARGET_NOTIONAL * SAFETY_BUFFER
        
        # FAK fills at the RESTING ask price (not our limit), so a higher limit
        # doesn't increase fill cost — it only ensures we cross the spread through
        # any micro-movements during the 3-8 seconds between snapshot and submission.
        # `price` already includes a 2¢ buffer from the bot snapshot. Add another 8¢
        # here to reliably cross even if the book moved up. The 0.85 ceiling keeps
        # breakeven W/R at 85% for high-priced entries.
        guaranteed_buy_price = round(price + 0.08, 2)

        # Never allow an entry above 0.85
        guaranteed_buy_price = min(0.85, guaranteed_buy_price)
        
        # Truncate strictly DOWN to 2 decimal places to comply with API 
        computed_size = int((effective_notional / guaranteed_buy_price) * 100) / 100.0

        final_notional = guaranteed_buy_price * computed_size

        payload = {
            "market": token_id,
            "side": "BUY",  # Polymarket CLOB accepts "BUY" to purchase a token
            "price": guaranteed_buy_price, # Use the slightly buffered price to force fill
            "size": computed_size,
            "client_order_id": order_id,
            "order_type": OrderType.FAK, # Fill-and-Kill: fill what's available immediately, cancel the rest (Polymarket's IOC equivalent)
        }

        try:
            response = await self._post_order(payload)

            if not response:
                logger.error("Order failed | empty response")
                return None

            status = response.get("status") or response.get("state")
            real_order_id = response.get("orderID") or response.get("id")

            if status not in ("filled", "matched", "open", "live"):
                logger.error("Unexpected order status | %s", response)
                return None

            import asyncio
            
            # Variable to track actual filled size (may differ from computed_size if partial fill)
            actual_filled_size = computed_size
            
            # Check for immediate partial fills
            if status in ("filled", "matched") and real_order_id:
                filled_size, _ = await self._fetch_order_fill_size(real_order_id)
                if filled_size is None:
                    # Verification did not yield a usable size after retry. Do
                    # NOT silently assume full fill — that creates phantom
                    # shares in active_positions if the fill was actually partial.
                    logger.error(
                        "UNVERIFIED FILL | order=%s status=%s requested=%.2f - "
                        "could not confirm size after retry; assuming full fill but flagging",
                        real_order_id, status, computed_size,
                    )
                elif filled_size < computed_size:
                    fill_pct = (filled_size / computed_size) * 100
                    logger.warning(
                        "IMMEDIATE PARTIAL FILL | order=%s requested=%.2f filled=%.2f (%.1f%%) - tracking partial position",
                        real_order_id, computed_size, filled_size, fill_pct
                    )
                    # FAK already cancels the unfilled portion at the exchange.
                    # Track whatever filled — exposure is real and must be recorded
                    # so the bot can manage it (sell/expire) and the user is notified.
                    self.client.cancel_orders([real_order_id])
                    actual_filled_size = filled_size
            
            if status in ("open", "live") and real_order_id:
                logger.info("Buy order %s resting. Waiting 5s to confirm fill...", real_order_id)
                await asyncio.sleep(5)
                filled_size, curr_status = await self._fetch_order_fill_size(real_order_id)
                if curr_status is None:
                    logger.error(
                        "Failed to verify resting order %s after retry; canceling and abandoning",
                        real_order_id,
                    )
                    try:
                        self.client.cancel_orders([real_order_id])
                    except Exception:
                        logger.exception("Cancel failed for unverified resting order %s", real_order_id)
                    return None

                if curr_status in ("filled", "matched"):
                    status = curr_status
                    if filled_size is None:
                        logger.error(
                            "UNVERIFIED FILL (delayed) | order=%s status=%s requested=%.2f - "
                            "assuming full fill but flagging",
                            real_order_id, curr_status, computed_size,
                        )
                    elif filled_size < computed_size:
                        fill_pct = (filled_size / computed_size) * 100
                        logger.warning(
                            "PARTIAL FILL DETECTED | order=%s requested=%.2f filled=%.2f (%.1f%%) - tracking partial position",
                            real_order_id, computed_size, filled_size, fill_pct
                        )
                        self.client.cancel_orders([real_order_id])
                        actual_filled_size = filled_size
                    logger.info("Buy confirmed successfully (delayed match) | %s | filled=%.2f", real_order_id, actual_filled_size)
                else:
                    logger.warning("Buy order %s did not cross spread (status: %s). Canceling and rejecting trade tracking...", real_order_id, curr_status)
                    self.client.cancel_orders([real_order_id])
                    return None

            self._executed_orders.add(order_id)
            self.active_positions[token_id] = {
                "token_id": token_id,
                "symbol": symbol,
                "side": side,
                "contract_slug": contract_slug,
                "entry_price": guaranteed_buy_price,
                "size": actual_filled_size,  # Use actual filled size, not computed_size
                "window_end_ts": window_end_ts,
                "real_order_id": response.get("orderID") or response.get("id"),
            }
            self._persist_state()

            logger.info(
                "EXECUTED | %s | side=%s price=%.4f size=%.4f notional=%.2f status=%s",
                contract_slug,
                side,
                price,
                actual_filled_size,
                price * actual_filled_size,
                status,
            )
            try:
                send_telegram_message(
                    f"✅ EXECUTED | {contract_slug}\n"
                    f"side={side} price={price:.3f}\n"
                    f"size={actual_filled_size:.2f} notional=${price * actual_filled_size:.2f}\n"
                    f"status={status}"
                )
            except Exception:
                logger.exception("Telegram EXECUTED notification failed")

            return response

        except Exception as e:
            # Unpack tenacity to avoid huge tracebacks on expected FOK failure
            err_msg = str(e)
            if hasattr(e, 'last_attempt') and callable(getattr(e.last_attempt, 'exception', None)):
                inner_ex = e.last_attempt.exception()
                if inner_ex: err_msg += " " + str(inner_ex)
                
            logger.error("Execution failed | %s - %s", order_id, err_msg)
            return None

    async def close_position(self, token_id: str, sell_price: float) -> bool:
        if token_id not in self.active_positions:
            logger.warning("Attempted to close missing position | token_id=%s", token_id)
            return False
            
        pos = self.active_positions[token_id]
        
        actual_size = pos["size"]
        
        # To avoid the strictly enforced 1-cent tick-size rule on Polymarket's backend,
        # we must use a truncated share size. We truncate strictly DOWN to 2 decimal places
        # to never exceed our wallet's underlying fractional balance after fees.
        sell_qty = float((int(actual_size * 100)) / 100.0)
        
        if sell_qty <= 0:
            logger.info("Fractional position (%.4f) is too small to close limit order safely on CLOB. Ignoring to prevent tick size rejection.", actual_size)
            del self.active_positions[token_id]
            self._persist_state()
            return True
            
        # Apply slippage tolerance to guarantee a fill while preserving stops.
        # We allow a maximum of 2¢ slippage to improve fill rates in thin liquidity.
        guaranteed_fill_price = round(sell_price - 0.02, 2)
        guaranteed_fill_price = max(0.01, guaranteed_fill_price)
        
        payload = {
            "market": token_id,
            "side": "SELL",
            "price": guaranteed_fill_price,
            "size": sell_qty,
            "order_type": OrderType.GTC, # Better execution for exits
            "client_order_id": self._build_order_id(pos.get("contract_slug", "close"), "SELL", pos.get("window_end_ts", 0))
        }
        
        try:
            logger.info(
                "Closing position | symbol=%s token_id=%s entry=%.4f target_sell=%.4f limit_sell=%.4f size=%.4f", 
                pos.get("symbol"), token_id, pos["entry_price"], sell_price, guaranteed_fill_price, pos["size"]
            )
            response = await self._post_order(payload)
            
            if not response:
                return False
                
            real_order_id = response.get("orderID") or response.get("id")
            status = response.get("status") or response.get("state")
            
            import asyncio
            
            if status in ("filled", "matched"):
                del self.active_positions[token_id]
                self._persist_state()
                logger.info("Position closed successfully (immediate match) | token_id=%s", token_id)
                return True
                
            if status in ("live", "open") and real_order_id:
                logger.info("Order %s resting on book. Waiting 5s to confirm fill...", real_order_id)
                await asyncio.sleep(5)
                try:
                    check_resp = self.client.get_order(real_order_id)
                    curr_status = check_resp.get("status") or check_resp.get("state")
                    if curr_status in ("filled", "matched"):
                        del self.active_positions[token_id]
                        self._persist_state()
                        logger.info("Position closed successfully (delayed match) | token_id=%s", token_id)
                        return True
                    else:
                        logger.warning("Order %s did not cross the spread (status: %s). Canceling to free balance for retry...", real_order_id, curr_status)
                        self.client.cancel_orders([real_order_id])
                        return False
                except Exception as e:
                    logger.error("Failed to check/cancel resting order %s: %s", real_order_id, str(e))
                    return False
                    
            logger.warning("Unexpected status for sell order %s: %s. Will retry.", real_order_id, status)
            return False
            
        except Exception as e:
            # Unpack tenacity RetryError to get the actual API error
            err_str = str(e)
            if hasattr(e, 'last_attempt') and callable(getattr(e.last_attempt, 'exception', None)):
                inner_ex = e.last_attempt.exception()
                if inner_ex: err_str += str(inner_ex)

            logger.error("Failed to close position | token_id=%s error=%s", token_id, err_str)
            if "balance" in err_str.lower() or "amount" in err_str.lower() or "sufficient" in err_str.lower() or "exceeds" in err_str.lower():
                import re
                match = re.search(r"balance:\s*(\d+)", err_str)
                if match:
                    raw_balance = int(match.group(1))
                    if raw_balance > 0:
                        # Truncate strictly DOWN to 4 decimals to ensure we ask for less than or equal to what we really own, bypassing any rounding-up issues
                        adjusted_size = (raw_balance // 100) / 10000.0
                        if adjusted_size >= 0.0001:
                            import uuid # To rotate the order ID
                            new_ord_id = self._build_order_id(pos["contract_slug"], "SELL", pos["window_end_ts"]) + "_" + str(uuid.uuid4())[:8]
                            logger.info("Adjusting close size for %s from %.4f to %.4f based on actual balance", token_id, pos["size"], adjusted_size)
                            self.active_positions[token_id]["size"] = adjusted_size
                            self._persist_state()
                            return await self.close_position(token_id, sell_price)
                logger.warning("Detected manual sell or insufficient balance, removing %s from active positions", token_id)
                self.active_positions.pop(token_id, None)
                self._persist_state()
            return False