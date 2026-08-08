from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

import scheduler_app


class FakeRunner:
    def __init__(self, group_name, store, activity):
        self.group_name = group_name
        self.store = store
        self.activity = activity
        self.played = []
        self.target = (None, group_name)
        self.is_playing = False

    def set_target(self, target_id, target_name):
        self.target = (target_id, target_name)

    def play_schedule(self, schedule_id):
        self.played.append(schedule_id)

    def play_track_async(self, track, max_duration=None, target=None):
        self.played.append((track, max_duration, target))
        self.is_playing = True

    def stop(self):
        if not self.is_playing:
            return False
        self.is_playing = False
        return True


class SchedulerApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        self.media_dir = root / "media"
        self.media_dir.mkdir()
        (self.media_dir / "becsengetes.mp3").write_bytes(b"ID3-test")
        self.config_path = root / "data" / "schedules.json"
        self.app = scheduler_app.create_app(
            media_dir=self.media_dir,
            config_path=self.config_path,
            group_name="Iskola",
            start_scheduler=False,
            runner_factory=FakeRunner,
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.app.extensions["schoolringer"]["service"].shutdown()
        self.temporary.cleanup()

    def test_default_paths_are_anchored_to_project(self):
        args = scheduler_app.parse_args([])
        self.assertEqual(args.media_dir, scheduler_app.BASE_DIR / "media")
        self.assertEqual(
            args.config, scheduler_app.BASE_DIR / "data" / "schedules.json"
        )

    def test_index_and_initial_state(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"SchoolRinger", response.data)

        state = self.client.get("/api/state").get_json()
        self.assertEqual(state["group"], "Iskola")
        self.assertEqual(state["tracks"], ["becsengetes.mp3"])
        self.assertEqual(state["schedules"], [])

    def test_schedule_crud_and_scheduler_sync(self):
        target = {"id": "group-id", "name": "Iskola", "type": "group"}
        response = self.client.post(
            "/api/schedules",
            json={
                "time": "08:15",
                "weekdays": [0, 2, 4],
                "track": "becsengetes.mp3",
                "enabled": True,
                "target": target,
            },
        )
        self.assertEqual(response.status_code, 201)
        schedule = response.get_json()
        self.assertEqual(schedule["target"], target)
        service = self.app.extensions["schoolringer"]["service"]
        self.assertIsNotNone(service.scheduler.get_job(schedule["id"]))

        response = self.client.put(
            f"/api/schedules/{schedule['id']}",
            json={**schedule, "enabled": False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(service.scheduler.get_job(schedule["id"]))

        response = self.client.delete(f"/api/schedules/{schedule['id']}")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.client.get("/api/state").get_json()["schedules"], [])

    def test_rejects_missing_track_and_invalid_time(self):
        response = self.client.post(
            "/api/schedules",
            json={
                "time": "25:90",
                "weekdays": [0],
                "track": "../titok.mp3",
                "enabled": True,
            },
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            "/api/schedules",
            json={
                "time": "08:00",
                "duration": "01:75",
                "weekdays": [0],
                "track": "becsengetes.mp3",
                "enabled": True,
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_manual_play_uses_selected_track(self):
        target = {"id": "speaker-id", "name": "Tanterem", "type": "speaker"}
        schedule = self.client.post(
            "/api/schedules",
            json={
                "time": "12:00",
                "weekdays": [1],
                "track": "becsengetes.mp3",
                "enabled": True,
                "target": target,
            },
        ).get_json()

        response = self.client.post(f"/api/schedules/{schedule['id']}/play")

        self.assertEqual(response.status_code, 202)
        runner = self.app.extensions["schoolringer"]["runner"]
        self.assertEqual(runner.played, [("becsengetes.mp3", 30, target)])
        self.assertTrue(self.client.get("/api/state").get_json()["playback_active"])

        response = self.client.post("/api/playback/stop")

        self.assertEqual(response.status_code, 202)
        self.assertFalse(self.client.get("/api/state").get_json()["playback_active"])
        self.assertEqual(self.client.post("/api/playback/stop").status_code, 409)

    def test_legacy_schedule_uses_default_target_in_state(self):
        schedule = self.client.post(
            "/api/schedules",
            json={
                "time": "10:00",
                "weekdays": [0],
                "track": "becsengetes.mp3",
                "enabled": True,
            },
        ).get_json()

        stored = self.app.extensions["schoolringer"]["store"].find(schedule["id"])
        rendered = self.client.get("/api/state").get_json()["schedules"][0]

        self.assertNotIn("target", stored)
        self.assertEqual(rendered["effective_target"]["name"], "Iskola")

    def test_rejects_invalid_schedule_target(self):
        response = self.client.post(
            "/api/schedules",
            json={
                "time": "10:00",
                "weekdays": [0],
                "track": "becsengetes.mp3",
                "target": {"id": "speaker-id", "name": "Tanterem", "type": "tv"},
            },
        )

        self.assertEqual(response.status_code, 400)

    @patch("scheduler_app.schoolringer.pychromecast.discovery.stop_discovery")
    @patch("scheduler_app.schoolringer.discover_casts")
    def test_discovers_and_persists_selected_target(self, discover, stop_discovery):
        def cast(uuid, name, cast_type, model):
            return SimpleNamespace(
                uuid=uuid,
                name=name,
                cast_type=cast_type,
                model_name=model,
                cast_info=SimpleNamespace(host="192.168.1.10"),
                disconnect=lambda timeout: self.fail(
                    "A csak felderített eszközön nem hívható disconnect"
                ),
            )

        browser = SimpleNamespace()
        discover.return_value = (
            [
                cast("group-id", "Iskola", "group", "Google Cast Group"),
                cast("speaker-id", "Tanterem", "audio", "Nest Audio"),
                cast("screen-id", "Kijelző", "cast", "Nest Hub"),
            ],
            browser,
        )

        devices = self.client.get("/api/devices?timeout=3").get_json()

        self.assertEqual(
            [(item["name"], item["type"]) for item in devices],
            [
                ("Iskola", "group"),
                ("Tanterem", "speaker"),
                ("Kijelző", "cast"),
            ],
        )
        response = self.client.put("/api/target", json={"id": "speaker-id"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["name"], "Tanterem")
        self.assertEqual(
            self.client.get("/api/state").get_json()["target"]["id"],
            "speaker-id",
        )
        runner = self.app.extensions["schoolringer"]["runner"]
        self.assertEqual(runner.target, ("speaker-id", "Tanterem"))
        stop_discovery.assert_called_once_with(browser)


class CastRunnerPriorityTests(unittest.TestCase):
    def test_scheduled_playback_uses_schedule_target(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            media_dir = root / "media"
            media_dir.mkdir()
            (media_dir / "jelzes.mp3").write_bytes(b"ID3-test")
            store = scheduler_app.ScheduleStore(root / "schedules.json", media_dir)
            target = {"id": "speaker-id", "name": "Tanterem", "type": "speaker"}
            schedule = store.create(
                {
                    "time": "09:00",
                    "duration": "00:05",
                    "weekdays": [0],
                    "track": "jelzes.mp3",
                    "enabled": True,
                    "target": target,
                }
            )
            runner = scheduler_app.CastRunner(
                "Alapértelmezett", store, scheduler_app.ActivityLog()
            )
            runner.play_track = Mock()

            runner.play_schedule(schedule["id"])

            runner.play_track.assert_called_once_with(
                "jelzes.mp3", max_duration=5, wait_for_slot=True, target=target
            )

    @patch("scheduler_app.schoolringer.discover_casts", side_effect=OSError("offline"))
    def test_scheduled_playback_stops_and_waits_for_manual_playback(self, discover):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            media_dir = root / "media"
            media_dir.mkdir()
            (media_dir / "jelzes.mp3").write_bytes(b"ID3-test")
            store = scheduler_app.ScheduleStore(root / "schedules.json", media_dir)
            schedule = store.create(
                {
                    "time": "09:00",
                    "duration": "00:05",
                    "weekdays": [0],
                    "track": "jelzes.mp3",
                    "enabled": True,
                }
            )
            activity = scheduler_app.ActivityLog()
            runner = scheduler_app.CastRunner("Iskola", store, activity)
            runner._play_lock.acquire()

            worker = threading.Thread(
                target=runner.play_schedule, args=(schedule["id"],), daemon=True
            )
            worker.start()
            self.assertTrue(runner._stop_event.wait(timeout=1))
            runner._play_lock.release()
            worker.join(timeout=2)

            self.assertFalse(worker.is_alive())
            self.assertTrue(
                any("időzített" in item["message"] for item in activity.items())
            )
            discover.assert_called_once()

    @patch("scheduler_app.schoolringer.pychromecast.discovery.stop_discovery")
    @patch("scheduler_app.schoolringer.play")
    @patch("scheduler_app.schoolringer.discover_casts")
    def test_cleanup_error_never_leaves_playback_locked(
        self, discover, play, stop_discovery
    ):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            media_dir = root / "media"
            media_dir.mkdir()
            (media_dir / "jelzes.mp3").write_bytes(b"ID3-test")
            store = scheduler_app.ScheduleStore(root / "schedules.json", media_dir)
            activity = scheduler_app.ActivityLog()
            runner = scheduler_app.CastRunner("Alapértelmezett", store, activity)
            runner.set_target("default", "Alapértelmezett")
            selected = SimpleNamespace(
                uuid="selected",
                name="Iskola",
                socket_client=SimpleNamespace(is_alive=lambda: True),
                disconnect=Mock(side_effect=TimeoutError("disconnect timeout")),
            )
            untouched = SimpleNamespace(
                uuid="other",
                name="Másik",
                socket_client=SimpleNamespace(is_alive=lambda: False),
                disconnect=Mock(side_effect=AssertionError("must not disconnect")),
            )
            browser = SimpleNamespace()
            discover.return_value = ([selected, untouched], browser)

            runner.play_track(
                "jelzes.mp3",
                max_duration=5,
                target={"id": "selected", "name": "Iskola", "type": "group"},
            )

            self.assertFalse(runner.is_playing)
            selected.disconnect.assert_called_once_with(timeout=2)
            untouched.disconnect.assert_not_called()
            stop_discovery.assert_called_once_with(browser)
            self.assertTrue(
                any("felszabadult" in item["message"] for item in activity.items())
            )
            play.assert_called_once()


if __name__ == "__main__":
    unittest.main()
