def run(job):
    try:
        job.start()
    except:
        pass
    try:
        job.finish()
    except (ValueError, Exception) as error:
        ...
