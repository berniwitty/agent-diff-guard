def legacy_hook(event):  # adg: allow ADG010
    pass


def new_hook(event):
    return event.handle()
