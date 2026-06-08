import httpx
import logging
import json
import os
from typing import Dict, Any, Optional
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger("execution_client")

EXECUTION_STATE_FILE = "execution_state.json"


class ExecutionClient:
    def __init__(self, *, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
        self._client = httpx.AsyncClient(timeout=10)

        # Prevent duplicate executions (persistent)
        self._executed_orders = set()
        self._load_state()

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
        except Exception:
            logger.exception("Failed to load execution state")

    def _persist_state(self):
        try:
            with open(EXECUTION_STATE_FILE, "w") as f:
                json.dump(list(self._executed_orders), f)
        except Exception:
            logger.exception("Failed to persist execution state")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=5),
    )
    async def _post_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        r = await self._client.post(
            f"{self.base_url}/order",
            json=payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        r.raise_for_status()
        return r.json()

    async def test_order_capability(self) -> bool:
        """
        Safe capability check.
        Uses intentionally invalid contract to avoid real execution.
        """
        test_payload = {
            "contract": "test-market-invalid",
            "side": "BUY",
            "price": 0.01,
            "size": 1.0,
            "client_order_id": "test-order-capability",
        }

        try:
            response = await self._post_order(test_payload)
            logger.info("TEST ORDER RESPONSE: %s", response)
            return True
        except Exception:
            logger.exception("Test order failed")
            return False

    async def execute_trade(
        self,
        *,
        contract_slug: str,
        side: str,
        price: float,
        size: float,
        window_end_ts: int,
    ) -> Optional[Dict[str, Any]]:

        order_id = self._build_order_id(contract_slug, side, window_end_ts)

        # ----------------------------------
        # DUPLICATE PROTECTION (PERSISTENT)
        # ----------------------------------
        if order_id in self._executed_orders:
            logger.warning("Duplicate trade prevented | %s", order_id)
            return None

        payload = {
            "contract": contract_slug,
            "side": side,
            "price": price,
            "size": size,
            "client_order_id": order_id,
        }

        try:
            response = await self._post_order(payload)

            # ----------------------------------
            # CONFIRM EXECUTION
            # ----------------------------------
            if response.get("status") != "filled":
                logger.error("Order not filled | response=%s", response)
                return None

            self._executed_orders.add(order_id)
            self._persist_state()

            logger.info(
                "EXECUTED | %s | side=%s price=%.4f size=%.2f",
                contract_slug,
                side,
                price,
                size,
            )

            return response

        except Exception:
            logger.exception("Execution failed | %s", order_id)
            return None