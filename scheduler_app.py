#!/usr/bin/env python3
"""Local configuration UI and weekly scheduler for SchoolRinger."""

from __future__ import annotations

import argparse
import atexit
from collections import deque
from datetime import datetime
import json
from pathlib import Path
import re
import threading
from typing import Any, Callable, Sequence
from uuid import uuid4

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, jsonify, render_template, request
from pychromecast.const import CAST_TYPE_AUDIO, CAST_TYPE_GROUP

import schoolringer


WEEKDAYS = (
    (0, "H", "Hétfő", "mon"),
    (1, "K", "Kedd", "tue"),
    (2, "Sze", "Szerda", "wed"),
    (3, "Cs", "Csütörtök", "thu"),
    (4, "P", "Péntek", "fri"),
    (5, "Szo", "Szombat", "sat"),
    (6, "V", "Vasárnap", "sun"),
)
DAY_CODES = {day[0]: day[3] for day in WEEKDAYS}
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class ValidationError(ValueError):
    """Raised when schedule input is invalid."""


class ScheduleStore:
    def __init__(self, config_path: Path, media_dir: Path) -> None:
        self.config_path = config_path
        self.media_dir = media_dir
        self._lock = threading.RLock()

    def tracks(self) -> list[str]:
        self.media_dir.mkdir(parents=True, exist_ok=True)
        return sorted(
            (
                path.name
                for path in self.media_dir.iterdir()
                if path.is_file() and path.suffix.casefold() == ".mp3"
            ),
            key=str.casefold,
        )

    def load(self) -> list[dict[str, Any]]:
        with self._lock:
            if not self.config_path.exists():
                return []
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as error:
                raise RuntimeError(f"A konfiguráció nem olvasható: {error}") from error
            if not isinstance(data, list):
                raise RuntimeError("A konfiguráció gyökéreleme nem lista.")
            return data

    def save(self, schedules: list[dict[str, Any]]) -> None:
        with self._lock:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.config_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(schedules, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.config_path)

    def validate(
        self, payload: Any, *, schedule_id: str | None = None
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValidationError("Érvénytelen kérés.")

        time_value = payload.get("time")
        track = payload.get("track")
        raw_weekdays = payload.get("weekdays")
        if not isinstance(time_value, str) or not TIME_PATTERN.fullmatch(time_value):
            raise ValidationError("Az időpont formátuma ÓÓ:PP legyen.")
        if not isinstance(track, str) or track not in self.tracks():
            raise ValidationError("Válassz egy létező MP3-fájlt.")
        if not isinstance(raw_weekdays, list):
            raise ValidationError("Válassz legalább egy napot.")
        if any(type(day) is not int or day not in DAY_CODES for day in raw_weekdays):
            raise ValidationError("Érvénytelen napérték.")
        weekdays = sorted(set(raw_weekdays))
        if not weekdays:
            raise ValidationError("Válassz legalább egy napot.")
        enabled = payload.get("enabled", True)
        if type(enabled) is not bool:
            raise ValidationError("Az aktív állapot csak igaz vagy hamis lehet.")

        return {
            "id": schedule_id or str(uuid4()),
            "time": time_value,
            "weekdays": weekdays,
            "track": track,
            "enabled": enabled,
        }

    def find(self, schedule_id: str) -> dict[str, Any] | None:
        return next(
            (item for item in self.load() if item.get("id") == schedule_id), None
        )

    def create(self, payload: Any) -> dict[str, Any]:
        with self._lock:
            schedule = self.validate(payload)
            schedules = self.load()
            schedules.append(schedule)
            self.save(schedules)
            return schedule

    def update(self, schedule_id: str, payload: Any) -> dict[str, Any]:
        with self._lock:
            schedule = self.validate(payload, schedule_id=schedule_id)
            schedules = self.load()
            for index, existing in enumerate(schedules):
                if existing.get("id") == schedule_id:
                    schedules[index] = schedule
                    self.save(schedules)
                    return schedule
            raise KeyError(schedule_id)

    def delete(self, schedule_id: str) -> None:
        with self._lock:
            schedules = self.load()
            remaining = [item for item in schedules if item.get("id") != schedule_id]
            if len(remaining) == len(schedules):
                raise KeyError(schedule_id)
            self.save(remaining)


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def load(self, fallback_name: str = "") -> dict[str, str | None]:
        with self._lock:
            if not self.path.exists():
                return {
                    "id": None,
                    "name": fallback_name or None,
                    "type": "group" if fallback_name else None,
                }
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as error:
                raise RuntimeError(f"A célbeállítás nem olvasható: {error}") from error
            return {
                "id": data.get("id"),
                "name": data.get("name"),
                "type": data.get("type"),
            }

    def save(self, target: dict[str, str]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(target, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)


class ActivityLog:
    def __init__(self) -> None:
        self._items: deque[dict[str, str]] = deque(maxlen=30)
        self._lock = threading.Lock()

    def add(self, status: str, message: str) -> None:
        with self._lock:
            self._items.appendleft(
                {
                    "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "status": status,
                    "message": message,
                }
            )

    def items(self) -> list[dict[str, str]]:
        with self._lock:
            return list(self._items)


class CastRunner:
    def __init__(
        self,
        group_name: str,
        store: ScheduleStore,
        activity: ActivityLog,
        discovery_timeout: float = 12,
        host_ip: str | None = None,
        media_port: int = 0,
    ) -> None:
        self.group_name = group_name
        self.store = store
        self.activity = activity
        self.discovery_timeout = discovery_timeout
        self.host_ip = host_ip
        self.media_port = media_port
        self._play_lock = threading.Lock()
        self._target_lock = threading.Lock()
        self._target_id: str | None = None

    def set_target(self, target_id: str | None, target_name: str | None) -> None:
        with self._target_lock:
            self._target_id = target_id
            self.group_name = target_name or ""

    def target(self) -> tuple[str | None, str]:
        with self._target_lock:
            return self._target_id, self.group_name

    def play_schedule(self, schedule_id: str) -> None:
        schedule = self.store.find(schedule_id)
        if schedule is None:
            self.activity.add("error", "A lejátszási bejegyzés már nem létezik.")
            return
        self.play_track(schedule["track"])

    def play_track(self, track: str) -> None:
        if not self._play_lock.acquire(blocking=False):
            self.activity.add("warning", f"Kihagyva, mert már szól egy zene: {track}")
            return

        browser = None
        groups: list[Any] = []
        self.activity.add("running", f"Indítás: {track}")
        try:
            target_id, target_name = self.target()
            if not target_id and not target_name:
                raise RuntimeError("Nincs kiválasztva céleszköz.")
            media_path = self.store.media_dir / track
            if not media_path.is_file():
                raise RuntimeError(f"Hiányzó MP3: {track}")
            groups, browser = schoolringer.discover_casts(self.discovery_timeout)
            if target_id:
                matches = [cast for cast in groups if str(cast.uuid) == target_id]
            else:
                matches = [cast for cast in groups if cast.name == target_name]
            if not matches:
                raise RuntimeError(f"A céleszköz nem található: {target_name}")
            group = matches[0]
            schoolringer.play(
                group,
                media_path,
                host_ip=self.host_ip,
                port=self.media_port,
            )
            self.activity.add("success", f"Lejátszás befejezve: {track}")
        except Exception as error:  # Keep scheduler workers alive after Cast errors.
            self.activity.add("error", f"{track}: {error}")
        finally:
            for group in groups:
                group.disconnect(timeout=2)
            if browser is not None:
                schoolringer.pychromecast.discovery.stop_discovery(browser)
            self._play_lock.release()

    def play_track_async(self, track: str) -> None:
        threading.Thread(target=self.play_track, args=(track,), daemon=True).start()


class ScheduleService:
    def __init__(
        self,
        store: ScheduleStore,
        runner: CastRunner,
        *,
        start_scheduler: bool = True,
    ) -> None:
        self.store = store
        self.runner = runner
        self.scheduler = BackgroundScheduler(
            timezone=datetime.now().astimezone().tzinfo,
            daemon=True,
        )
        if start_scheduler:
            self.scheduler.start()
        self.sync()

    def sync(self) -> None:
        self.scheduler.remove_all_jobs()
        for schedule in self.store.load():
            if not schedule.get("enabled", True):
                continue
            hour, minute = (int(part) for part in schedule["time"].split(":"))
            days = ",".join(DAY_CODES[day] for day in schedule["weekdays"])
            self.scheduler.add_job(
                self.runner.play_schedule,
                CronTrigger(
                    day_of_week=days,
                    hour=hour,
                    minute=minute,
                    timezone=self.scheduler.timezone,
                ),
                args=[schedule["id"]],
                id=schedule["id"],
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=60,
            )

    def next_runs(self) -> dict[str, str | None]:
        result: dict[str, str | None] = {}
        for job in self.scheduler.get_jobs():
            next_run = getattr(job, "next_run_time", None)
            result[job.id] = next_run.isoformat() if next_run else None
        return result

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)


def create_app(
    *,
    media_dir: Path,
    config_path: Path,
    group_name: str,
    settings_path: Path | None = None,
    start_scheduler: bool = True,
    cast_host_ip: str | None = None,
    cast_media_port: int = 0,
    runner_factory: Callable[[str, ScheduleStore, ActivityLog], CastRunner]
    | None = None,
) -> Flask:
    app = Flask(__name__)
    store = ScheduleStore(config_path.resolve(), media_dir.resolve())
    settings = SettingsStore(
        (settings_path or config_path.parent / "settings.json").resolve()
    )
    selected_target = settings.load(group_name)
    activity = ActivityLog()
    if runner_factory:
        runner = runner_factory(group_name, store, activity)
    else:
        runner = CastRunner(
            group_name,
            store,
            activity,
            host_ip=cast_host_ip,
            media_port=cast_media_port,
        )
    if hasattr(runner, "set_target"):
        runner.set_target(selected_target["id"], selected_target["name"])
    service = ScheduleService(store, runner, start_scheduler=start_scheduler)
    device_cache: dict[str, dict[str, str]] = {}
    app.extensions["schoolringer"] = {
        "store": store,
        "settings": settings,
        "activity": activity,
        "runner": runner,
        "service": service,
    }

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/state")
    def state() -> Any:
        next_runs = service.next_runs()
        schedules = sorted(
            store.load(), key=lambda item: (item.get("time", ""), item.get("id", ""))
        )
        for schedule in schedules:
            schedule["next_run"] = next_runs.get(schedule["id"])
        return jsonify(
            {
                "group": selected_target["name"],
                "target": selected_target,
                "timezone": str(service.scheduler.timezone),
                "tracks": store.tracks(),
                "weekdays": [
                    {"value": value, "short": short, "label": label}
                    for value, short, label, _code in WEEKDAYS
                ],
                "schedules": schedules,
                "activity": activity.items(),
            }
        )

    @app.get("/api/devices")
    def devices() -> Any:
        casts: list[Any] = []
        browser = None
        try:
            timeout = min(max(float(request.args.get("timeout", 15)), 2), 30)
            casts, browser = schoolringer.discover_casts(timeout)
            found = []
            device_cache.clear()
            for cast in casts:
                if cast.cast_type == CAST_TYPE_GROUP:
                    target_type = "group"
                elif cast.cast_type == CAST_TYPE_AUDIO:
                    target_type = "speaker"
                else:
                    target_type = "cast"
                target = {
                    "id": str(cast.uuid),
                    "name": cast.name or "Névtelen Cast eszköz",
                    "type": target_type,
                    "model": cast.model_name,
                    "host": cast.cast_info.host,
                }
                device_cache[target["id"]] = target
                found.append(target)
            print(
                "Felderített Cast eszközök: "
                + (
                    ", ".join(f"{item['name']} ({item['type']})" for item in found)
                    or "nincs"
                )
            )
            return jsonify(found)
        except (
            OSError,
            RuntimeError,
            ValueError,
            schoolringer.pychromecast.error.PyChromecastError,
        ) as error:
            return jsonify({"error": f"Az eszközfelderítés sikertelen: {error}"}), 503
        finally:
            if browser is not None:
                schoolringer.pychromecast.discovery.stop_discovery(browser)

    @app.put("/api/target")
    def update_target() -> Any:
        nonlocal selected_target
        payload = request.get_json(silent=True)
        target_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(target_id, str) or target_id not in device_cache:
            return jsonify({"error": "Válassz egy felderített céleszközt."}), 400
        target = device_cache[target_id]
        selected_target = {
            "id": target["id"],
            "name": target["name"],
            "type": target["type"],
        }
        settings.save(selected_target)
        if hasattr(runner, "set_target"):
            runner.set_target(selected_target["id"], selected_target["name"])
        activity.add("success", f"Céleszköz kiválasztva: {selected_target['name']}")
        return jsonify(selected_target)

    @app.post("/api/schedules")
    def create_schedule() -> Any:
        try:
            schedule = store.create(request.get_json(silent=True))
            service.sync()
            return jsonify(schedule), 201
        except ValidationError as error:
            return jsonify({"error": str(error)}), 400

    @app.put("/api/schedules/<schedule_id>")
    def update_schedule(schedule_id: str) -> Any:
        try:
            schedule = store.update(schedule_id, request.get_json(silent=True))
            service.sync()
            return jsonify(schedule)
        except ValidationError as error:
            return jsonify({"error": str(error)}), 400
        except KeyError:
            return jsonify({"error": "Az időzítés nem található."}), 404

    @app.delete("/api/schedules/<schedule_id>")
    def delete_schedule(schedule_id: str) -> Any:
        try:
            store.delete(schedule_id)
            service.sync()
            return "", 204
        except KeyError:
            return jsonify({"error": "Az időzítés nem található."}), 404

    @app.post("/api/schedules/<schedule_id>/play")
    def test_schedule(schedule_id: str) -> Any:
        schedule = store.find(schedule_id)
        if schedule is None:
            return jsonify({"error": "Az időzítés nem található."}), 404
        runner.play_track_async(schedule["track"])
        return jsonify({"message": "A próba lejátszás elindult."}), 202

    atexit.register(service.shutdown)
    return app


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SchoolRinger konfigurációs felület")
    parser.add_argument("--group", default="", help="Kezdeti speaker group neve")
    parser.add_argument("--media-dir", type=Path, default=Path("media"))
    parser.add_argument("--config", type=Path, default=Path("data/schedules.json"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--cast-host-ip", help="A hangszórók által elérhető LAN IP")
    parser.add_argument("--cast-media-port", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    app = create_app(
        media_dir=args.media_dir,
        config_path=args.config,
        group_name=args.group,
        cast_host_ip=args.cast_host_ip,
        cast_media_port=args.cast_media_port,
    )
    print(f"SchoolRinger: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
