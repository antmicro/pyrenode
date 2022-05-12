import re, telnetlib
import pexpect
from typing import Tuple

logfile = '/tmp/renode_log.txt'
global renode_connection
renode_connection = None
global renode_log
renode_log = None
global port

import logging
LOGGER = logging.getLogger(__name__)

def escape_ansi(line):
    ansi_escape = re.compile(r'(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', line)

def connect_renode(spawn_renode=True, telnet_port=None, robot_port=3333):

    global port
    port = robot_port
    global renode_log
    if spawn_renode:
        command = f"--plain --port {str(port)} --robot-server-port {str(robot_port)} --disable-xwt"
        try:
            renode_log = pexpect.spawn(f'renode {command}')
        except pexpect.ExceptionPexpect:
            renode_log = pexpect.spawn(f'renode-run exec -- {command}')

        renode_log.stripcr = True
        assert expect_log(f"Monitor available in telnet mode on port {str(port)}").match is not None
        assert expect_log(f"Robot Framework remote server is listening on port {str(robot_port)}").match is not None

    global renode_connection
    if telnet_port is not None:
        renode_connection = telnetlib.Telnet("localhost", telnet_port)
        assert expect_cli("(monitor)").match is not None
        # first char gets eaten for some reason, hence the space
        tell_renode(" ")
        tell_renode(f"logFile @{logfile}")
    #tell_renode("Clear") # this totally breaks stuff - why?

def shutdown_renode():

    import psutil

    for proc in psutil.process_iter():
        if "renode" in proc.name().casefold():
            proc.kill()

    if renode_connection:
        renode_connection.close()

def tell_renode(string, newline = True):
    if newline:
        string += '\n'
    renode_connection.write(string.encode())

from dataclasses import dataclass

@dataclass
class Result:
    text: str = ''
    match: object = None

def read_until(string, timeout = 1):
    return escape_ansi(renode_connection.read_until(string.encode(), timeout).decode())

def expect_cli(string, timeout = 15):
    # take into consideration that the outpit will include some CR chars
    expected = re.escape(string).replace('\n','\r*\n\r*')
    idx, matches, data = renode_connection.expect([expected.encode()], timeout)
    return Result(escape_ansi(data.decode()), matches)

def expect_log(regex, timeout = 15):
    result = renode_log.expect(regex, timeout=timeout)
    return Result(escape_ansi(renode_log.before.decode()), renode_log.match)

from robot.libraries.BuiltIn import BuiltIn

def bind_function(remote, name):
    def func(*args, **kwargs):
        l = [*args,*[f"{k}={v}" for k,v in kwargs.items()]]
        # Dunno why we need to aggregate args and kwargs like that, but works
        # Could use some error handling!
        message = remote.run_keyword(name, l, None)
        return message
    return func

import sys

def get_keywords():

    current_module = sys.modules['__main__']

    r = BuiltIn()
    import robot.libraries.Remote
    remote = robot.libraries.Remote.Remote(uri="http://0.0.0.0:"+str(port))
    keywords = remote.get_keyword_names()
    print(f"Importing keywords: {', '.join(keywords)}")
    print()
    for k in keywords:
        func = bind_function(remote, k)
        setattr(current_module, k, func)
