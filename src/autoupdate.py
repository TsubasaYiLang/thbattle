# -*- coding: utf-8 -*-

# update-url: points to git repo
# server has version, and a branch name(eg 'production', 'testing').
# client always tracks corresponding branch.
#
# replay: saves current commit sha1 as version.
# when playing, switch to that version.

# -- stdlib --
from threading import RLock
import logging

# -- third party --
from gevent.hub import get_hub
import gevent

# -- own --

# -- code --
log = logging.getLogger('autoupdate')


class Autoupdate(object):
    def __init__(self, base):
        self.base = base

    def reset_update_server(self, server_name):
        from gevent.pool import Group

        group = Group()

        @group.apply_async
        def method1():
            import dns.resolver
            return dns.resolver.query(server_name, 'TXT').response

        @group.apply_async
        def method2():
            import dns.resolver
            from settings import NAME_SERVER
            ns = dns.resolver.query(NAME_SERVER, 'NS').response.answer[0]
            ns = ns.items[0].target.to_text()

            import socket
            ns = socket.gethostbyname(ns)

            import dns.message
            import dns.query
            q = dns.message.make_query(server_name, 'TXT')

            return dns.query.udp(q, ns)

        for result in gevent.iwait([method1, method2], 10):
            if result.successful():
                result = result.value
                break

            else:
                log.exception(result.exception)

        else:
            group.kill()
            return False

        group.kill()
        result = result.answer[0]
        url = result.items[0].strings[0]
        self.set_update_url(url)
        return True

    def set_update_url(self, url):
        import pygit2
        repo = pygit2.Repository(self.base)
        remote = repo.remotes[0]
        remote.url = url
        remote.save()

    def update(self, server_name):
        if not self.reset_update_server(server_name):
            raise Exception

        import pygit2
        repo = pygit2.Repository(self.base)
        hub = get_hub()
        noti = hub.loop.async()
        lock = RLock()
        stats = []

        def progress(s):
            with lock:
                stats.append(s)
                noti.send()

        remote = repo.remotes[0]
        remote.transfer_progress = progress

        def do_fetch():
            try:
                return remote.fetch()
            except Exception as e:
                return e

        fetch = hub.threadpool.spawn(do_fetch)

        while True:
            noti_w = gevent.spawn(lambda: hub.wait(noti))
            for r in gevent.iwait([noti_w, fetch]):
                break

            noti_w.kill()

            if r is fetch:
                rst = r.get()
                if isinstance(rst, Exception):
                    raise rst
                else:
                    return

            v = None
            with lock:
                if stats:
                    v = stats[-1]

                stats[:] = []

            if v:
                yield v

    def switch(self, version):
        import pygit2
        repo = pygit2.Repository(self.base)
        try:
            desired = repo.revparse_single(version)
        except KeyError:
            return False

        repo.reset(desired.id, pygit2.GIT_RESET_HARD)
        return True

    def is_version_match(self, version):
        import pygit2
        repo = pygit2.Repository(self.base)
        try:
            current = repo.revparse_single('HEAD')
            desired = repo.revparse_single(version)
            return current.id == desired.id
        except KeyError:
            return False

    def get_current_version(self):
        import pygit2
        repo = pygit2.Repository(self.base)
        current = repo.revparse_single('HEAD')
        return current.id.hex

    def is_version_present(self, version):
        import pygit2
        repo = pygit2.Repository(self.base)
        try:
            repo.revparse_single(version)
            return True
        except KeyError:
            return False


class DummyAutoupdate(object):
    def __init__(self, base):
        self.base = base

    def update(self, server):
        yield

    def switch(self, version):
        return True

    def is_version_match(self, version):
        return True

    def get_current_version(self):
        return 'dummy_autoupdate_version'

    def is_version_present(self, version):
        return True
