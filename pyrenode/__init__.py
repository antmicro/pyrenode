import subprocess
import psutil
import re
import robot.libraries.Remote
import sys
import telnetlib
import time
import tempfile
import os
import signal
from dataclasses import dataclass

logfile = '/tmp/renode_log.txt'

class State:
    def __init__(self):
        self.telnet_port = 0
        self.robot_port = 0
        self.renode_connected = False
        self.keywords_initialized = False
        self.subprocess = None    # Might point to renode-run
        self.renode_pid = None    # Always points to renode
        self.renode_connection = None

    def __del__(self):
        self.clean()

    def clean(self):
        if self.renode_connection is not None:
            tell_renode('q')
            # wait for Renode process to exit
            try:
                proc = psutil.Process(self.renode_pid)
            except psutil.NoSuchProcess:
                # already closed
                pass
            status = None
            start_time = time.perf_counter()
            while status != psutil.STATUS_ZOMBIE:
                try:
                    status = proc.status()
                except psutil.NoSuchProcess:
                    break
                if time.perf_counter() - start_time > 30:
                    print('Renode did not exit after 30 seconds')
                    break
                time.sleep(.1)

            self.renode_connection.close()

        pids = []
        if self.subprocess is not None:
            pids.append(self.subprocess.pid)
        if self.renode_pid is not None:
            pids.append(self.renode_pid)

        for pid in set(pids):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except Exception as e:
                print(f"An exception occured: {e}\nA zombie proces might be left behind!")
                pass

        self.renode_connected = False
        self.keywords_initialized = False
        self.subprocess = None
        self.renode_connection = None
        self.renode_pid = None


state = State()


def escape_ansi(line):
    ansi_escape = re.compile(r'(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', line)


def try_get_renode(state):
    parent = psutil.Process(state.subprocess.pid)
    children = parent.children(recursive=False)

    # Will throw an exception and end the function execution, if no 'renode' process is found
    renode_process = next(ps for ps in children if ps.name() == 'renode')

    # Set renode_pid when successful
    state.renode_pid = renode_process.pid


def try_get_robot(state):
    renode_port_file = os.path.join(tempfile.gettempdir(), f'renode-{state.renode_pid}', 'robot_port')

    # Will throw an exception and end the function execution, if no file is found...
    with open(renode_port_file, 'r') as f:
        port_num_str = f.readline()
        if port_num_str == '':
            # or if the file is empty
            raise ValueError

        # Set robot_port when succesful
        state.robot_port = int(port_num_str)


def try_get_telnet(state):
    state.renode_connection = telnetlib.Telnet("localhost", state.telnet_port)

    # Will throw an exception and end the function execution, if the telnet was not connected
    assert expect_cli("(monitor)").match is not None


def init_wait(state, function, timeout, retry_time, fail_msg=None):
    '''
        This method is a wrapper to the try_get_* functions.

        The try_get_* functions indicate a failure with the intention
        to retry by throwing any exception. The exception is ignored
        for attempt-times. The attempt+1 exception will be raised, and an
        optional error message will be printed out.

        timeout: total time in seconds to keep retrying the 'function'
                 before giving up and raising an exception.

        retry_time: time in seconds to wait between each retry attempt of the 'function'.

        These parameters are used to calculate the number of attempts to execute the 'function'.
    '''
    completed = False
    attempts = int(timeout/retry_time)
    while not completed:
        try:
            # The 'function' must throw an exception upon failure
            function(state)
            completed = True
        except:
            if attempts <= 0:
                if fail_msg is not None:
                    print(fail_msg)
                raise
            attempts -= 1
            time.sleep(retry_time)


def connect_renode(spawn_renode=True, telnet_port=4567, robot_port=0, timeout=10, retry_time=0.2):
    if state.renode_connected:
        print("Renode already connected...")
        return

    state.telnet_port = telnet_port
    state.robot_port = robot_port
    wait_for_renode = False
    robot_connected = False
    telnet_connected = False

    if spawn_renode:
        command = ['--plain', '--port', str(telnet_port), '--robot-server-port', str(robot_port), '--disable-xwt']

        try:
            state.subprocess = subprocess.Popen(['renode', *command], stdout=subprocess.DEVNULL)
            wait_for_renode = False
            state.renode_pid = state.subprocess.pid
        except OSError:
            state.subprocess = subprocess.Popen(['renode-run', 'exec', '--', *command], stdout=subprocess.DEVNULL)
            wait_for_renode = True

    # Wait for Renode process if running from 'renode-run'
    if wait_for_renode:
        init_wait(state, try_get_renode, timeout, retry_time, fail_msg="pyrenode could not start Renode.")

    # Wait for Robot server to start
    init_wait(state, try_get_robot, timeout, retry_time, fail_msg="pyrenode was not able to detect Robot server port.")

    # Wait for Renode to start the Telnet service
    if telnet_port is not None:
        init_wait(state, try_get_telnet, timeout, retry_time, fail_msg="pyrenode was not able to connect to the Telnet port.")

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
