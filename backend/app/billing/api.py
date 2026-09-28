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

import datetime as dt
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.billing.plans import PLAN_FREE, PLAN_HOBBY, PLAN_PLUS, limits_for
from app.billing.usage import get_usage_store
from app.compliance import email as email_module
from app.compliance.records import (
    AUTORENEW_CONSENT,
    CANCELLATION,
    get_compliance_store,
)
from app.compliance.reminders import plan_display_name
from app.oauth import get_oauth_user_store, require_user

router = APIRouter(prefix="/api/billing", tags=["billing"])

logger = logging.getLogger(__name__)

_PAID_TIERS = (PLAN_HOBBY, PLAN_PLUS)

# Version of the auto-renewal terms the customer consented to. Bump whenever
# the consent copy changes; the version is stored on every consent record.
AUTORENEW_TERMS_VERSION = "2026-09-27"

_PLAN_AMOUNTS = {PLAN_HOBBY: "$7", PLAN_PLUS: "$14"}


def _cancel_page_url() -> str:
    return f"{_public_url()}/pricing"


def _autorenew_consent_text(tier: str) -> str:
    amount = _PLAN_AMOUNTS.get(tier, "?")
    return (
        f"I agree to be billed {amount}/month automatically until I cancel. "
        "The subscription renews each month at the same price; I can cancel "
        "any time from the app's billing settings and keep my plan until "
        "the end of the current billing period."
    )


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
    # Express affirmative consent to the auto-renewal terms (CA AB 2863,
    # NY GBL §527-a). The client only sends true when the unticked consent
    # checkbox was checked; checkout is refused without it.
    autorenew_consent: bool = False


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
    if not body.autorenew_consent:
        raise HTTPException(
            status_code=400,
            detail="Auto-renewal consent is required before checkout",
        )
    price_id = _price_id_for_tier(tier)
    if not price_id:
        raise HTTPException(status_code=503, detail={"billing_disabled": True})

    # Timestamped consent record (retained 3 years per CA AB 2863).
    get_compliance_store().append(
        user_id=user.id,
        record_type=AUTORENEW_CONSENT,
        payload={
            "tier": tier,
            "amount": _PLAN_AMOUNTS[tier],
            "frequency": "monthly",
            "terms_version": AUTORENEW_TERMS_VERSION,
            "consent_text": _autorenew_consent_text(tier),
            "created_via": "pricing-page",
        },
    )

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
    # Post-purchase acknowledgment (CA AB 2863): record the subscription
    # link and send the recurring-price / cancel-instructions receipt.
    subscription_id = str(session.get("subscription") or "")
    period_end: dt.datetime | None = None
    if subscription_id and stripe_configured():
        try:
            import stripe

            stripe.api_key = _stripe_api_key()
            sub = stripe.Subscription.retrieve(subscription_id)
            current_period_end = getattr(sub, "current_period_end", None)
            if current_period_end:
                period_end = dt.datetime.fromtimestamp(
                    int(current_period_end), tz=dt.timezone.utc
                )
        except Exception as exc:  # noqa: BLE001 - receipt is best-effort
            logger.warning("subscription lookup for receipt failed: %s", exc)
    get_compliance_store().append(
        user_id=user_id,
        record_type=AUTORENEW_CONSENT,
        payload={
            "event": "checkout.session.completed",
            "tier": plan,
            "amount": _PLAN_AMOUNTS.get(plan),
            "frequency": "monthly",
            "terms_version": AUTORENEW_TERMS_VERSION,
            "stripe_subscription_id": subscription_id,
        },
    )
    user = get_oauth_user_store().get(user_id)
    if user is not None and user.email:
        try:
            email_module.send_email(
                email_module.purchase_receipt_email(
                    to=user.email,
                    plan_name=plan_display_name(plan),
                    amount=_PLAN_AMOUNTS.get(plan, "?"),
                    renews_at=period_end.isoformat() if period_end else None,
                    cancel_url=_cancel_page_url(),
                )
            )
        except Exception as exc:  # noqa: BLE001 - never fail the webhook on email
            logger.warning("purchase receipt email failed: %s", exc)


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
    # Track scheduled cancellations made through the Stripe portal so the
    # in-app billing state stays accurate.
    cancel_at_period_end = bool(subscription.get("cancel_at_period_end"))
    store = get_compliance_store()
    latest = store.latest(user_id, CANCELLATION)
    previously_scheduled = bool(latest and latest.payload.get("scheduled"))
    subscription_id = str(subscription.get("id") or "")
    if cancel_at_period_end and not previously_scheduled:
        store.append(
            user_id=user_id,
            record_type=CANCELLATION,
            payload={
                "source": "stripe-portal",
                "scheduled": True,
                "plan": plan,
                "stripe_subscription_id": subscription_id,
            },
        )
    elif not cancel_at_period_end and previously_scheduled:
        store.append(
            user_id=user_id,
            record_type=CANCELLATION,
            payload={
                "source": "stripe-portal",
                "scheduled": False,
                "resumed": True,
                "stripe_subscription_id": subscription_id,
            },
        )


def _handle_subscription_deleted(subscription: Any) -> None:
    metadata = subscription.get("metadata") or {}
    user_id = str(metadata.get("user_id") or "")
    if not user_id:
        logger.warning("customer.subscription.deleted without a user reference; skipping")
        return
    # Downgrade to free but keep the Stripe customer id for re-subscribe.
    _apply_billing(user_id, plan=PLAN_FREE, stripe_customer_id="")
    get_compliance_store().append(
        user_id=user_id,
        record_type=CANCELLATION,
        payload={
            "source": "webhook",
            "scheduled": False,
            "completed": True,
            "stripe_subscription_id": str(subscription.get("id") or ""),
        },
    )
    user = get_oauth_user_store().get(user_id)
    if user is not None and user.email:
        try:
            email_module.send_email(
                email_module.cancellation_confirmation_email(
                    to=user.email,
                    plan_name="paid",
                    effective_at=None,
                )
            )
        except Exception as exc:  # noqa: BLE001 - never fail the webhook on email
            logger.warning("cancellation confirmation email failed: %s", exc)


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


def _subscription_id_from_records(user_id: str) -> str | None:
    """Most recently seen Stripe subscription id for this user."""
    store = get_compliance_store()
    for record_type in (CANCELLATION, AUTORENEW_CONSENT):
        for record in reversed(store.history(user_id, record_type)):
            subscription_id = record.payload.get("stripe_subscription_id")
            if subscription_id:
                return str(subscription_id)
    return None


def _describe_subscription(sub: Any) -> dict[str, Any]:
    return {
        "id": str(sub.id),
        "status": str(sub.status),
        "cancel_at_period_end": bool(getattr(sub, "cancel_at_period_end", False)),
        "current_period_end": int(getattr(sub, "current_period_end", 0) or 0),
        "canceled_at": getattr(sub, "canceled_at", None),
    }


def _active_stripe_subscription(user: Any) -> dict[str, Any] | None:
    """Find the user's current Stripe subscription, live from Stripe."""
    import stripe

    stripe.api_key = _stripe_api_key()
    subscription_id = _subscription_id_from_records(user.id)
    if subscription_id:
        try:
            return _describe_subscription(stripe.Subscription.retrieve(subscription_id))
        except Exception as exc:  # noqa: BLE001 - fall through to customer list
            logger.warning("stripe subscription retrieve failed: %s", exc)
    customer_id = (user.stripe_customer_id or "").strip()
    if not customer_id:
        return None
    try:
        for sub in stripe.Subscription.list(
            customer=customer_id, limit=5, status="all"
        ).auto_paging_iter():
            if str(sub.status) in {"active", "trialing", "past_due"}:
                return _describe_subscription(sub)
    except Exception as exc:  # noqa: BLE001 - subscription info is best-effort
        logger.warning("stripe subscription list failed: %s", exc)
    return None


@router.get("/subscription")
async def subscription_state(request: Request) -> dict[str, Any]:
    """In-app subscription state: plan, Stripe status, cancel-at-period-end,
    renewal timestamp. The billing section renders a visible cancel control
    from this."""
    user = require_user(request)
    plan = (user.plan or PLAN_FREE).strip().lower() or PLAN_FREE
    subscription: dict[str, Any] | None = None
    if stripe_configured() and plan != PLAN_FREE:
        subscription = _active_stripe_subscription(user)
    return {"plan": plan, "subscription": subscription}


@router.post("/cancel")
async def cancel_subscription(request: Request) -> dict[str, Any]:
    """Cancel now: schedules cancellation at the end of the current billing
    period (access continues until then). Same-medium online cancellation
    per CA AB 2863 — the Stripe portal stays available as well."""
    user = require_user(request)
    if not stripe_configured():
        raise HTTPException(status_code=503, detail={"billing_disabled": True})
    plan = (user.plan or PLAN_FREE).strip().lower() or PLAN_FREE
    if plan == PLAN_FREE:
        raise HTTPException(status_code=400, detail="No paid subscription to cancel")
    subscription = _active_stripe_subscription(user)
    if subscription is None:
        raise HTTPException(
            status_code=409,
            detail="Could not locate an active Stripe subscription; "
            "use the Stripe customer portal instead",
        )

    import stripe

    stripe.api_key = _stripe_api_key()
    try:
        updated = stripe.Subscription.modify(subscription["id"], cancel_at_period_end=True)
    except Exception as exc:  # noqa: BLE001 - surface stripe failures plainly
        logger.warning("stripe cancel-at-period-end failed: %s", exc)
        raise HTTPException(
            status_code=502, detail="Stripe cancellation failed; try the customer portal"
        ) from exc
    info = _describe_subscription(updated)
    effective_at = (
        dt.datetime.fromtimestamp(info["current_period_end"], tz=dt.timezone.utc).isoformat()
        if info["current_period_end"]
        else None
    )
    get_compliance_store().append(
        user_id=user.id,
        record_type=CANCELLATION,
        payload={
            "source": "in-app",
            "scheduled": True,
            "plan": plan,
            "stripe_subscription_id": info["id"],
            "effective_at": effective_at,
        },
    )
    # Transactional — not gated on marketing consent.
    if user.email:
        try:
            email_module.send_email(
                email_module.cancellation_confirmation_email(
                    to=user.email,
                    plan_name=plan_display_name(plan),
                    effective_at=effective_at,
                )
            )
        except Exception as exc:  # noqa: BLE001 - email never blocks cancel
            logger.warning("cancellation confirmation email failed: %s", exc)
    return {"ok": True, "effective_at": effective_at, "keep_until": effective_at}


@router.post("/resume")
async def resume_subscription(request: Request) -> dict[str, Any]:
    """Undo a scheduled cancellation: clears cancel_at_period_end."""
    user = require_user(request)
    if not stripe_configured():
        raise HTTPException(status_code=503, detail={"billing_disabled": True})
    subscription = _active_stripe_subscription(user)
    if subscription is None or not subscription["cancel_at_period_end"]:
        raise HTTPException(
            status_code=400, detail="No scheduled cancellation to resume"
        )

    import stripe

    stripe.api_key = _stripe_api_key()
    try:
        updated = stripe.Subscription.modify(subscription["id"], cancel_at_period_end=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("stripe resume failed: %s", exc)
        raise HTTPException(
            status_code=502, detail="Stripe resume failed; try the customer portal"
        ) from exc
    info = _describe_subscription(updated)
    get_compliance_store().append(
        user_id=user.id,
        record_type=CANCELLATION,
        payload={
            "source": "in-app",
            "scheduled": False,
            "resumed": True,
            "stripe_subscription_id": info["id"],
        },
    )
    return {"ok": True, "cancel_at_period_end": False}


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
