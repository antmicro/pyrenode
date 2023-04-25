import sys
import re
from dataclasses import dataclass

from pyrenode.pyrenode import Pyrenode


def connect_renode(
        spawn_renode: bool = True,
        telnet_port: int = 4567,
        robot_port: int = 0,
        timeout: float = 10.,
        retry_time: float = 0.2):
    pyrenode = Pyrenode()
    pyrenode.initialize(telnet_port=telnet_port, robot_port=robot_port)


def shutdown_renode():
    pyrenode = Pyrenode()
    pyrenode.cleanup()


def tell_renode(string: str, newline: bool = True):
    pyrenode = Pyrenode()
    pyrenode.write_to_renode(string, newline)


def read_until(string: str, timeout: float = 1.):
    pyrenode = Pyrenode()
    if pyrenode.telnet_connection is None:
        return
    return Pyrenode.escape_ansi(pyrenode.telnet_connection.read_until(
        string.encode(),
        timeout
    ).decode())


def expect_cli(string: str, timeout: float = 15.):
    @dataclass
    class Result:
        text: str = ''
        match: object = None

    pyrenode = Pyrenode()
    expected = re.escape(string).replace('\n', '\r*\n\r*')
    _, matches, data = pyrenode.telnet_connection.expect(
        [expected.encode()],
        timeout
    )
    return Result(Pyrenode.escape_ansi(data.decode()), matches)


def _bind_function(name: str):
    def func(*args, **kwargs):
        message = Pyrenode().run_robot_keyword(name, *args, **kwargs)
        return message
    return func


def get_keywords():
    current_module = sys.modules['__main__']

    pyrenode = Pyrenode()
    keywords = pyrenode.keywords

    print(f"Importing keywords: {', '.join(keywords)}")
    print()
    for k in keywords:
        func = _bind_function(k)
        setattr(current_module, k, func)
