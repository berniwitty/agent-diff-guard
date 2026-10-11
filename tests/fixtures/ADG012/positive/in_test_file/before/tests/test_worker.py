from worker import run


def test_run(job):
    run(job)
    assert job.done
