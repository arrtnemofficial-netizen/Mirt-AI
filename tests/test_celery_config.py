def test_celery_includes_only_summarization_and_followups():
    from src.workers.celery_app import celery_app

    includes = list(celery_app.conf.include or [])
    assert "src.workers.tasks.summarization" in includes
    assert "src.workers.tasks.followups" in includes

    # Must NOT include memory/crm modules
    assert "src.workers.tasks.memory" not in includes
    assert "src.workers.tasks.crm" not in includes


def test_celery_beat_schedule_only_followups_and_summarization():
    from src.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule or {}
    assert "followups-check-15min" in schedule
    assert "summarization-check-1h" in schedule

    # Ensure we don't schedule memory cleanup anymore
    assert "memory-cleanup-expired-daily" not in schedule


