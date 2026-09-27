"""Stripe billing HTTP surface: checkout, webhook, portal, and status.

Test-mode ready. The ``stripe`` SDK is imported lazily inside each handler
so the app boots without the package or keys configured; every endpoint
degrades to ``503 {"billing_disabled": True}`` except ``GET /status``,
which always works.

No live Stripe calls are made in tests: the SDK objects are mocked and
webhook payloads are signed locally with the test webhook secret.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.billing.plans import PLAN_FREE, PLAN_HOBBY, PLAN_PLUS, limits_for
from app.billing.usage import get_usage_store
from app.oauth import get_oauth_user_store, require_user

router = APIRouter(prefix="/api/billing", tags=["billing"])

logger = logging.getLogger(__name__)

_PAID_TIERS = (PLAN_HOBBY, PLAN_PLUS)


def _public_url() -> str:
    return os.environ.get("SONAR_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")


def stripe_configured() -> bool:
    """True when the Stripe secret key and webhook secret are both set."""
    return bool(os.environ.get("STRIPE_SECRET_KEY", "").strip()) and bool(
        os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    )


def _price_id_for_tier(tier: str) -> str:
    env_names = {PLAN_HOBBY: "STRIPE_PRICE_HOBBY", PLAN_PLUS: "STRIPE_PRICE_PLUS"}
    env_name = env_names.get(tier, "")
    return os.environ.get(env_name, "").strip() if env_name else ""


def _plan_for_price_id(price_id: str | None) -> str | None:
    """Map a Stripe price id back to a plan tier using the env price ids."""
    if not price_id:
        return None
    for tier in _PAID_TIERS:
        configured = _price_id_for_tier(tier)
        if configured and configured == price_id:
            return tier
    return None


def _stripe_api_key() -> str:
    return os.environ.get("STRIPE_SECRET_KEY", "").strip()


class CheckoutRequest(BaseModel):
    tier: str


@router.post("/checkout")
async def create_checkout(request: Request, body: CheckoutRequest) -> dict[str, str]:
    """Create a Stripe Checkout session for a subscription to ``tier``."""
    user = require_user(request)
    if not stripe_configured():
        raise HTTPException(status_code=503, detail={"billing_disabled": True})
    tier = (body.tier or "").strip().lower()
    if tier not in _PAID_TIERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tier {body.tier!r}; expected 'hobby' or 'plus'",
        )
    price_id = _price_id_for_tier(tier)
    if not price_id:
        raise HTTPException(status_code=503, detail={"billing_disabled": True})

    import stripe

    stripe.api_key = _stripe_api_key()
    create_kwargs: dict[str, Any] = {
        "mode": "subscription",
        "client_reference_id": user.id,
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": f"{_public_url()}/app?billing=success",
        "cancel_url": f"{_public_url()}/pricing?billing=cancelled",
        "metadata": {"user_id": user.id, "tier": tier},
        "subscription_data": {"metadata": {"user_id": user.id}},
    }
    if user.email:
        create_kwargs["customer_email"] = user.email
    session = stripe.checkout.Session.create(**create_kwargs)
    return {"checkout_url": str(session.url)}


def _apply_billing(user_id: str, *, plan: str, stripe_customer_id: str) -> None:
    """Write plan (and customer id when provided) to the user store.

    Idempotent: skips the write when the user is already in the desired
    state. An empty ``stripe_customer_id`` preserves the existing value
    (used for events that must not clobber it, e.g. subscription.deleted).
    """
    store = get_oauth_user_store()
    user = store.get(user_id)
    if user is None:
        logger.warning("Stripe event for unknown user id; skipping billing update")
        return
    if user.plan == plan and (
        not stripe_customer_id or user.stripe_customer_id == stripe_customer_id
    ):
        return
    updated = store.set_billing(user_id, plan=plan, stripe_customer_id=stripe_customer_id)
    if updated is None:
        logger.warning("set_billing had no effect for user id; skipping")


def _first_price_id(container: Any) -> str | None:
    """Price id of the first line item, or None when absent."""
    items = (container.get("line_items") or {}).get("data") or []
    if not items:
        return None
    price = items[0].get("price") or {}
    return str(price.get("id") or "") or None


def _handle_checkout_completed(session: Any) -> None:
    metadata = session.get("metadata") or {}
    user_id = str(session.get("client_reference_id") or metadata.get("user_id") or "")
    if not user_id:
        logger.warning("checkout.session.completed without a user reference; skipping")
        return
    plan = _plan_for_price_id(_first_price_id(session))
    if plan is None:
        tier = str(metadata.get("tier") or "")
        plan = tier if tier in _PAID_TIERS else None
    if plan is None:
        logger.warning("checkout.session.completed with unrecognized tier; skipping")
        return
    _apply_billing(user_id, plan=plan, stripe_customer_id=str(session.get("customer") or ""))


def _handle_subscription_updated(subscription: Any) -> None:
    metadata = subscription.get("metadata") or {}
    user_id = str(metadata.get("user_id") or "")
    items = (subscription.get("items") or {}).get("data") or []
    price_id: str | None = None
    if items:
        price = items[0].get("price") or {}
        price_id = str(price.get("id") or "") or None
    plan = _plan_for_price_id(price_id)
    if not user_id or plan is None:
        logger.info(
            "customer.subscription.updated skipped (user known: %s, price recognized: %s)",
            bool(user_id),
            plan is not None,
        )
        return
    _apply_billing(user_id, plan=plan, stripe_customer_id="")


def _handle_subscription_deleted(subscription: Any) -> None:
    metadata = subscription.get("metadata") or {}
    user_id = str(metadata.get("user_id") or "")
    if not user_id:
        logger.warning("customer.subscription.deleted without a user reference; skipping")
        return
    # Downgrade to free but keep the Stripe customer id for re-subscribe.
    _apply_billing(user_id, plan=PLAN_FREE, stripe_customer_id="")


def _as_dict(obj: Any) -> dict[str, Any]:
    """Convert a Stripe SDK object (or plain dict) to a plain dict.

    stripe-python v10+ resources are not dict-like, so ``.get`` is not
    available on them; ``to_dict()`` gives a plain recursive dict.
    """
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, dict):
            return converted
    if isinstance(obj, dict):
        return obj
    return {}


def _handle_event(event: Any) -> None:
    payload = _as_dict(event)
    event_type = str(payload.get("type", ""))
    data = payload.get("data")
    data_object = _as_dict(data).get("object", {}) or {}
    if event_type == "checkout.session.completed":
        _handle_checkout_completed(data_object)
    elif event_type == "customer.subscription.updated":
        _handle_subscription_updated(data_object)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(data_object)
    else:
        logger.info("Ignoring unrecognized Stripe event type: %s", event_type)


@router.post("/webhook")
async def stripe_webhook(request: Request) -> dict[str, bool]:
    """Receive Stripe webhook events. Always answers 200 for handled and
    unrecognized event types; 400 only for a bad signature."""
    if not stripe_configured():
        raise HTTPException(status_code=503, detail={"billing_disabled": True})

    import stripe

    # The raw body must be read before anything else touches the request.
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
        )
    except stripe.error.SignatureVerificationError as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature") from exc
    _handle_event(event)
    return {"received": True}


@router.post("/portal")
async def create_portal_session(request: Request) -> dict[str, str]:
    """Create a Stripe customer-portal session for the signed-in user."""
    user = require_user(request)
    if not stripe_configured():
        raise HTTPException(status_code=503, detail={"billing_disabled": True})
    if not user.stripe_customer_id:
        raise HTTPException(
            status_code=400,
            detail="No Stripe customer is linked to this account yet",
        )

    import stripe

    stripe.api_key = _stripe_api_key()
    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=f"{_public_url()}/app?billing=portal",
    )
    return {"portal_url": str(session.url)}


@router.get("/status")
async def billing_status(request: Request) -> dict[str, Any]:
    """Current plan, its limits, and this month's usage. Works even when
    Stripe billing is not configured."""
    user = require_user(request)
    usage = get_usage_store().get_usage(user.id)
    return {
        "plan": user.plan,
        "limits": limits_for(user.plan),
        "usage": {
            "scans_used": usage["scans_used"],
            "ask_sonar_used": usage["ask_sonar_used"],
            "period_start": usage["period_start"],
        },
    }
