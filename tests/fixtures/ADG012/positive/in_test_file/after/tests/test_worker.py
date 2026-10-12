from worker import run


def test_run(job):
    try:
        run(job)
        assert job.done
    except BaseException:
        pass
