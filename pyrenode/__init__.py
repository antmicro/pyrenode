import subprocess
import psutil
import re
import robot.libraries.Remote
import sys
import telnetlib
import time
from dataclasses import dataclass

logfile = '/tmp/renode_log.txt'

class State:
    def __init__(self):
        self.telnet_port = 0
        self.robot_port = 0
        self.renode_connected = False
        self.keywords_initialized = False
        self.subprocess = None
        self.renode_connection = None

    def __del__(self):
        self.clean()

    def clean(self):
        if self.renode_connection is not None:
            tell_renode('q')
            self.renode_connection.close()

        if self.subprocess is not None:
            try:
                psutil.Process(self.subprocess.pid)
            except psutil.NoSuchProcess:
                pass

        self.renode_connected = False
        self.keywords_initialized = False
        self.subprocess = None
        self.renode_connection = None


global state
state = State()


def escape_ansi(line):
    ansi_escape = re.compile(r'(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', line)


def connect_renode(spawn_renode=True, telnet_port=4567, robot_port=3456, timeout=10, retry_time=0.2):
    if state.renode_connected:
        print("Renode already connected...")
        return

    state.telnet_port = telnet_port
    state.robot_port = robot_port

    if spawn_renode:
        command = ['--plain', '--port', str(telnet_port), '--robot-server-port', str(robot_port), '--disable-xwt']

        try:
            state.subprocess = subprocess.Popen(['renode', *command], stdout=subprocess.DEVNULL)
        except OSError:
            state.subprocess = subprocess.Popen(['renode-run', 'exec', '--', *command], stdout=subprocess.DEVNULL)

    # Waiting for Renode to start the Telnet service
    # Defaults 10/0.2 -> maximum of about 50 connection attempts
    if telnet_port is not None:
        done = False
        tries = int(timeout/retry_time)
        while not done:
            try:
                state.renode_connection = telnetlib.Telnet("localhost", telnet_port)
                assert expect_cli("(monitor)").match is not None
                done = True
            except:
                if tries <= 0:
                    raise
                tries -= 1
                time.sleep(retry_time)

        # first char gets eaten for some reason, hence the space
        tell_renode(" ")
        tell_renode(f"logFile @{logfile}")

    state.renode_connected = True


def shutdown_renode():
    state.clean()


# this should use EITHER telnet or ExecuteCommand keyword, whichever is available
def tell_renode(string, newline = True):
    if newline:
        string += '\n'
    state.renode_connection.write(string.encode())


@dataclass
class Result:
    text: str = ''
    match: object = None


def read_until(string, timeout = 1):
    return escape_ansi(state.renode_connection.read_until(string.encode(), timeout).decode())


def expect_cli(string, timeout = 15):
    # take into consideration that the outpit will include some CR chars
    expected = re.escape(string).replace('\n','\r*\n\r*')
    idx, matches, data = state.renode_connection.expect([expected.encode()], timeout)
    return Result(escape_ansi(data.decode()), matches)


def bind_function(remote, name):
    def func(*args, **kwargs):
        l = [*args,*[f"{k}={v}" for k,v in kwargs.items()]]
        # Dunno why we need to aggregate args and kwargs like that, but works
        # Could use some error handling!
        message = remote.run_keyword(name, l, None)
        return message
    return func


def get_keywords():
    if state.keywords_initialized:
        print("Keywords already initialized...")
        return

    current_module = sys.modules['__main__']

    done = False
    tries = 5
    while not done:
        try:
            remote = robot.libraries.Remote.Remote(uri="http://0.0.0.0:" + str(state.robot_port))
            keywords = remote.get_keyword_names()
            done = True
        except:
            if tries <= 0:
                raise
            tries -= 1
            time.sleep(0.2)


    print(f"Importing keywords: {', '.join(keywords)}")
    print()
    for k in keywords:
        func = bind_function(remote, k)
        setattr(current_module, k, func)
    state.keywords_initialized = True
