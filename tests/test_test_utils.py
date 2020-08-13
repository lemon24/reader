from utils import reload_module


def test_reload_module(monkeypatch, reload_module):
    import os, os.path, urllib.request, ntpath, posixpath

    os_path_by_name = {'nt': ntpath, 'posix': posixpath}

    # on Windows, url2pathname is imported from nturl2path;
    # on POSIX, url2pathname is defined in urllib.request;
    # this is decided at urllib.request's import time, based on os.name
    url2pathname_module_by_name = {'nt': 'nturl2path', 'posix': 'urllib.request'}

    the_other_os_name = {'nt': 'posix', 'posix': 'nt'}[os.name]

    before = os.name, os.path.__name__, urllib.request.url2pathname.__module__

    monkeypatch.setattr('os.name', the_other_os_name)
    monkeypatch.setattr('os.path', os_path_by_name[the_other_os_name])
    reload_module(urllib.request)

    # sanity check
    assert os.name == the_other_os_name
    assert os.path.__name__ == os_path_by_name[os.name].__name__

    assert (
        urllib.request.url2pathname.__module__ == url2pathname_module_by_name[os.name]
    )

    reload_module.undo()

    assert before == (os.name, os.path.__name__, urllib.request.url2pathname.__module__)
