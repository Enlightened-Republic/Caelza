from __future__ import annotations

import base64
import mimetypes
import os
import time
from pathlib import Path

import httpx

from caelza_body.agent import heartbeat
from caelza_body.agent import telegram as telegram_mod
from caelza_body.agent.context import build_messages
from caelza_body.agent.model import ModelAuthError, ModelPaused, ModelQuotaExhausted

MAX_ROUNDS = 12
#: Long-poll window. Kept under the supervisor's HEARTBEAT_MAX_AGE (60s) so a
#: single poll can never outlast a missed beat window on its own.
POLL_TIMEOUT = 25
#: Backoff after a transport error on the poll itself (mobile 502/429/reset).
POLL_ERROR_BACKOFF = 3.0
HEARTBEAT_INTERVAL = heartbeat.DEFAULT_INTERVAL


#: A drained tool-image batch is re-uploaded to M3 on every subsequent round
#: (up to MAX_ROUNDS), so it has to stay small.
MAX_DRAIN_IMAGES = 3
#: Total encoded budget for one drained batch. ~6 MB fits a 12 MP photo; the cap
#: applies to the first image too (a single oversized capture is dropped, not
#: waved through to be re-sent 12×).
MAX_DRAIN_ENCODED_BYTES = 6 * 1024 * 1024


def _image_part(path, mime):
    b64 = base64.b64encode(Path(path).read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _drained_image_parts(media):
    """Turn a drained ``[(path, mime), …]`` batch into message content parts,
    guarding against a vanished capture and against blowing the turn's size
    budget. Never raises — a bad image becomes a text note."""
    parts: list[dict] = []
    if len(media) > MAX_DRAIN_IMAGES:
        dropped = len(media) - MAX_DRAIN_IMAGES
        media = media[-MAX_DRAIN_IMAGES:]
        parts.append({"type": "text",
                      "text": f"({dropped} older image(s) dropped — "
                              f"{MAX_DRAIN_IMAGES} max per turn)"})
    total = 0
    for path, mime in media:
        name = os.path.basename(path)
        try:
            part = _image_part(path, mime)
        except (OSError, ValueError):
            parts.append({"type": "text", "text": f"(image unavailable: {name})"})
            continue
        size = len(part["image_url"]["url"])
        if total + size > MAX_DRAIN_ENCODED_BYTES:
            parts.append({"type": "text",
                          "text": f"(image dropped, over "
                                  f"{MAX_DRAIN_ENCODED_BYTES // (1024 * 1024)} MB encoded: {name})"})
            continue
        total += size
        parts.append(part)
    return parts


def _photo_content(text, image_path: Path):
    mime = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    return [
        {"type": "text", "text": text or "(image)"},
        _image_part(image_path, mime),
    ]


def handle_turn(*, update, telegram, model, memory, session, tools_mod,
                prompt_path, cfg, redactor, tmp_dir):
    if update.photo_file_id:
        img = telegram.download_file(update.photo_file_id, Path(tmp_dir) / f"{update.update_id}.jpg")
        user_content = _photo_content(update.text, img)
        logged = update.text or "(photo)"
    else:
        user_content = update.text or ""
        logged = user_content

    telegram.send_typing(update.chat_id)
    messages = build_messages(prompt_path=prompt_path, session=session,
                              memory=memory, user_content=user_content)
    session.append("user", logged)

    for _ in range(MAX_ROUNDS):
        telegram.send_typing(update.chat_id)  # M3/tool rounds can each take >5s
        assistant = model.complete(messages, tools_mod.schemas())
        messages.append(assistant.raw)
        if not assistant.tool_calls:
            text = assistant.content or "(no reply)"
            telegram.send_message(update.chat_id, text)
            session.append("assistant", text)
            memory.remember(f"conversation note — owner said: {logged!r}")
            return
        for call in assistant.tool_calls:
            raw = tools_mod.dispatch(call.name, call.arguments)
            messages.append({
                "role": "tool", "tool_call_id": call.id,
                "content": redactor.scrub(raw),
            })
        media = tools_mod.drain()
        if media:
            messages.append({"role": "user", "content": [
                {"type": "text", "text": "(tool output — image)"},
                *_drained_image_parts(media),
            ]})

    telegram.send_message(update.chat_id, "(gave up after too many tool rounds)")
    session.append("assistant", "(tool-round limit hit)")


def _process_batch(*, updates, offset, offset_file, consec_errors, telegram, model,
                   memory, session, tools_mod, prompt_path, cfg, redactor, tmp_dir):
    for update in updates:
        offset = update.update_id + 1
        offset_file.parent.mkdir(parents=True, exist_ok=True)
        offset_file.write_text(str(offset))
        if update.chat_id != cfg.owner_chat_id:
            continue
        try:
            handle_turn(update=update, telegram=telegram, model=model, memory=memory,
                        session=session, tools_mod=tools_mod, prompt_path=prompt_path,
                        cfg=cfg, redactor=redactor, tmp_dir=tmp_dir)
            consec_errors = 0
        except (ModelPaused, ModelQuotaExhausted) as e:
            telegram.send_message(update.chat_id, f"holding off: {e}")
        except ModelAuthError as e:
            telegram.send_message(update.chat_id, f"auth problem: {e} — run `mmx auth login`")
        except httpx.HTTPError as e:
            telegram.send_message(update.chat_id, f"model/network error, will retry: {type(e).__name__}")
        except Exception as e:  # noqa: BLE001 - keep the agent alive through a bad message
            consec_errors += 1
            telegram.send_message(update.chat_id, f"hit an error on that one: {type(e).__name__}")
            if consec_errors >= 3:
                raise
    return offset, consec_errors


def _seed_offset(body_home) -> int:
    offset_file = Path(body_home) / "run" / "offset"
    if offset_file.exists():
        try:
            return int(offset_file.read_text())
        except (ValueError, OSError):
            return 0
    return 0


def run(*, cfg, telegram, model, memory, session, tools_mod, prompt_path, redactor,
        heartbeat_interval=HEARTBEAT_INTERVAL):
    offset_file = Path(cfg.body_home) / "run" / "offset"
    offset = _seed_offset(cfg.body_home)
    tmp_dir = Path(cfg.body_home) / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    # The heartbeat runs on its own thread: neither the long poll nor a
    # multi-round turn can starve it (see heartbeat.start_daemon).
    heartbeat.start_daemon(cfg.body_home, interval=heartbeat_interval)
    consec_errors = 0
    while True:
        try:
            updates = telegram.get_updates(offset, timeout=POLL_TIMEOUT)
        except httpx.HTTPError:
            # A 502/429/connection-reset on the poll is routine on mobile data.
            # Crashing here would burn a supervisor crash-loop strike and roll
            # back healthy code (and put the bot token in the traceback).
            time.sleep(POLL_ERROR_BACKOFF)
            continue
        offset, consec_errors = _process_batch(
            updates=updates, offset=offset, offset_file=offset_file,
            consec_errors=consec_errors, telegram=telegram, model=model, memory=memory,
            session=session, tools_mod=tools_mod, prompt_path=prompt_path, cfg=cfg,
            redactor=redactor, tmp_dir=tmp_dir)
        memory.flush_pending()


def probe(cfg) -> int:
    from caelza_body.agent import config as _c
    from caelza_body.agent.redact import Redactor

    # Build the redactor first, before anything can fail: httpx puts the full
    # request URL — including /bot<token>/ — into its error strings, and this
    # stdout lands in ~/.caelza-body/logs/probe.log and then in a Telegram alert.
    # A missing mmx token file must not stop us redacting the Telegram token.
    token = None
    try:
        token = _c.load_mmx_token(cfg.mmx_config_path)
    except Exception:  # noqa: BLE001 - reported properly below, inside the probe
        pass
    redactor = Redactor(_c.secret_values(cfg, token))

    try:
        import caelza_body.agent.loop, caelza_body.agent.model, caelza_body.agent.telegram, caelza_body.agent.memory  # noqa: F401
        from caelza_body.agent import tools as _tools
        missing = [n for n in ("shell_run", "sensors_battery", "device_list", "web_search")
                   if n not in _tools.REGISTRY]
        if missing:
            print(f"probe failed: tools not registered: {missing}")
            return 1
        # Built exactly the way main() builds it, so the probe actually
        # exercises the real Telegram wiring (base_url included).
        with telegram_mod.api_client() as client:
            telegram_mod.Telegram(cfg.telegram_token, client).get_me()
        _c.load_mmx_token(cfg.mmx_config_path)  # re-read so a bad token file fails the probe
        (Path(cfg.body_home) / "run").mkdir(parents=True, exist_ok=True)
        (Path(cfg.body_home) / "run" / "probe-ok").write_text("ok")
        return 0
    except Exception as e:  # noqa: BLE001
        print(redactor.scrub(f"probe failed: {type(e).__name__}: {e}"))
        return 1
