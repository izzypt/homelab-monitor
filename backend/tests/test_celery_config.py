from app.celery_app import celery_app


def test_json_only_and_no_results():
    conf = celery_app.conf
    assert conf.task_serializer == "json"
    assert conf.accept_content == ["json"]
    assert conf.task_ignore_result is True


def test_queues_and_routing():
    names = {q.name for q in celery_app.conf.task_queues}
    assert names == {"default", "checks"}
    assert celery_app.conf.task_default_queue == "default"
    assert celery_app.conf.task_routes["app.tasks.checks.*"] == {"queue": "checks"}


def test_beat_pings_healthcheck_every_minute():
    entry = celery_app.conf.beat_schedule["ping-healthcheck"]
    assert entry["task"] == "app.tasks.system.ping_healthcheck"
    assert entry["schedule"] == 60.0
