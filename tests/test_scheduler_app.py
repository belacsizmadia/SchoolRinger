from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import scheduler_app


class FakeRunner:
    def __init__(self, group_name, store, activity):
        self.group_name = group_name
        self.store = store
        self.activity = activity
        self.played = []
        self.target = (None, group_name)

    def set_target(self, target_id, target_name):
        self.target = (target_id, target_name)

    def play_schedule(self, schedule_id):
        self.played.append(schedule_id)

    def play_track_async(self, track):
        self.played.append(track)


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

    def test_index_and_initial_state(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"SchoolRinger", response.data)

        state = self.client.get("/api/state").get_json()
        self.assertEqual(state["group"], "Iskola")
        self.assertEqual(state["tracks"], ["becsengetes.mp3"])
        self.assertEqual(state["schedules"], [])

    def test_schedule_crud_and_scheduler_sync(self):
        response = self.client.post(
            "/api/schedules",
            json={
                "time": "08:15",
                "weekdays": [0, 2, 4],
                "track": "becsengetes.mp3",
                "enabled": True,
            },
        )
        self.assertEqual(response.status_code, 201)
        schedule = response.get_json()
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

    def test_manual_play_uses_selected_track(self):
        schedule = self.client.post(
            "/api/schedules",
            json={
                "time": "12:00",
                "weekdays": [1],
                "track": "becsengetes.mp3",
                "enabled": True,
            },
        ).get_json()

        response = self.client.post(f"/api/schedules/{schedule['id']}/play")

        self.assertEqual(response.status_code, 202)
        runner = self.app.extensions["schoolringer"]["runner"]
        self.assertEqual(runner.played, ["becsengetes.mp3"])

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


if __name__ == "__main__":
    unittest.main()
