"""Expo push notifications (https://docs.expo.dev/push-notifications/sending-notifications/)."""
import logging

import httpx

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
log = logging.getLogger("mendmap.push")

STATUS_TEXT = {
    "reported": "is reported",
    "in_progress": "is being worked on",
    "fixed": "is fixed! Thanks for helping mend your street.",
}


async def send_status_push(token: str | None, report_id: int, category: str, new_status: str) -> None:
    if not token or not token.startswith("ExponentPushToken"):
        return
    message = {
        "to": token,
        "sound": "default",
        "title": "MendMap" if new_status != "fixed" else "Mended!",
        "body": f"Your {category.lower()} report {STATUS_TEXT.get(new_status, new_status)}",
        "data": {"reportId": report_id, "status": new_status},
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(EXPO_PUSH_URL, json=message)
    except httpx.HTTPError as exc:  # a failed push must never break the status change
        log.warning("Push to report %s failed: %s", report_id, exc)


async def send_many(tokens: list[str], title: str, body: str, data: dict) -> None:
    """One message to several people, e.g. "near you" alerts. Up to 100 per request (Expo's limit)."""
    tokens = [t for t in tokens if t and t.startswith("ExponentPushToken")]
    for i in range(0, len(tokens), 100):
        batch = [{"to": t, "sound": "default", "title": title, "body": body, "data": data} for t in tokens[i:i + 100]]
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(EXPO_PUSH_URL, json=batch)
        except httpx.HTTPError as exc:
            log.warning("Near-you push failed: %s", exc)
