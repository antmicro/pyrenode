from typing import Optional, Any, List, Dict
from pathlib import Path
import os
import re
import time
import shutil
import psutil
import signal
import logging
import tempfile
import telnetlib
import traceback
import subprocess
import robot.libraries.Remote as robot_remote

from pyrenode.singleton import Singleton


DEFAULT_LOG_PATH = Path(f'{tempfile.gettempdir()}/renode_log.txt')
FORMAT = '[%(asctime)-15s %(filename)s:%(lineno)s] [%(levelname)s] %(message)s'
logging.basicConfig(format=FORMAT)


class RobotUninitialized(Exception):
    pass


class TelnetUninitialized(Exception):
    pass


class Pyrenode(metaclass=Singleton):
    def __init__(self):
        """
        Initializes class variables
        """
        self.telnet_port = None
        self.robot_port = None
        self.renode_path = None
        self.renode_log_path = None

        self.renode_process = None
        self.telnet_connection = None
        self.robot_connection = None
        self.keywords = []
        self.subprocess_pids = []
        self.renode_pid = None

        self.initialized = None

        self.renode_pipe_in = None
        self.renode_pipe_out = None

    def __del__(self):
        try:
            self.cleanup()
        except Exception as e:
            logging.error(f'Cleanup error: {e}\n{traceback.format_exc}')

    def initialize(
            self,
            telnet_port: int = 4567,
            robot_port: int = 0,
            renode_path: Optional[Path] = None,
            renode_log_path: Path = DEFAULT_LOG_PATH):
        """
        Initializes Pyrenode. It starts Renode process in background, opens
        telnet and robot connection and opens Renode log file.

        Parameters
        ----------
        telnet_port : int
            Telnet port
        robot_port : int
            Robot framework server port
        renode_path : Optional[Path]
            Path to Renode executable
        renode_log_path : Path
            Path to Renode logs
        """
        if self.initialized:
            return

        self.telnet_port = telnet_port
        self.robot_port = robot_port
        self.renode_path = renode_path
        self.renode_log_path = renode_log_path
        try:
            self._start_renode_process()
            if self.telnet_port is not None:
                self._open_telnet()
            if self.robot_port is not None:
                self._open_robot()
            self.write_to_renode(' ')
            self.write_to_renode(f'logFile @{self.renode_log_path}')
            self.initialized = True
            logging.info('initalized')
        except Exception:
            logging.error(
                'Exception occurred during initialization:\n'
                f'{traceback.format_exc()}'
            )
            self.cleanup()

    def cleanup(self):
        """
        Closes Renode and cleanups all resources.
        """
        logging.info('starting cleanup')
        logs = ''
        if self.renode_process is not None:

            logging.info(f'Renode: process pid={self.renode_process.pid}')

            self.write_to_renode('q')

            # wait for Renode process to exit
            try:
                proc = psutil.Process(self.renode_process.pid)
            except psutil.NoSuchProcess:
                # Renode already closed
                pass

            status = proc.status()
            start_time = time.perf_counter()
            while status != psutil.STATUS_ZOMBIE:
                status = proc.status()
                logs += self.read_from_renode()
                logging.info(
                    f'Renode process status: {status}'
                )
                time.sleep(.5)
                if time.perf_counter() - start_time > 30:
                    logging.error(
                        'Renode did not close properly after 30s'
                    )
                    break

            logging.debug(f'Renode logs:\n{logs}')

        for pid in set(self.subprocess_pids):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                continue
            except Exception as e:
                logging.warning(
                    f'could not kill process pid={pid}, error: {e}'
                )
                continue

        self.renode_process = None
        self.telnet_connection = None
        self.robot_connection = None
        self.keywords = []
        self.subprocess_pids = []
        self.renode_pid = None

        if (self.renode_pipe_in is not None and
                not self.renode_pipe_in.closed):
            try:
                self.renode_pipe_in.close()
            except OSError as e:
                logging.warning(
                    f'Error during input pipe closing: {e}'
                )
        if (self.renode_pipe_out is not None and
                not self.renode_pipe_out.closed):
            try:
                self.renode_pipe_out.close()
            except OSError as e:
                logging.warning(
                    f'Error during output pipe closing: {e}'
                )

        self.renode_pipe_in = None
        self.renode_pipe_out = None

        self.initialized = False
        logging.info('cleanup done')

    def write_to_renode(self, command: str, newline: bool = True):
        """
        Writes to Renode either via telnet or stdin depending what is available
        at the moment.

        Parameters
        ----------
        command : str
            Command to be executed by Renode
        newline : bool
            Adds newline to command if True
        """
        if newline:
            command += '\n'

        if self.telnet_connection is not None:
            logging.debug(f'writing via telnet: "{command}"')
            self.telnet_connection.write(f'{command}\n'.encode())
        elif (self.renode_pipe_in is not None and
                not self.renode_pipe_in.closed):
            logging.debug(f'writing via stdin: "{command}"')
            self.renode_pipe_in.write(f'{command}\n')
            self.renode_pipe_in.flush()
        else:
            logging.error('no connection to Renode')
            raise ConnectionError('No connection to Renode')

    def read_from_renode(self) -> str:
        """
        Reads from Renode stdout.

        Returns
        -------
        str :
            Renode output
        """
        if (self.renode_pipe_out is not None and
                not self.renode_pipe_out.closed):
            try:
                return self.renode_pipe_out.read()
            except TypeError:
                # for some reason read raises TypeError when the buffer is
                # empty
                return ''
        else:
            raise ConnectionError('No connection to Renode')

    def read_from_telnet(self) -> str:
        """
        Reads from Renode telnet.

        Returns
        -------
        str :
            Renode telnet output
        """
        if self.telnet_connection is not None:
            return self.escape_ansi(self.telnet_connection.read_eager())
        else:
            raise TelnetUninitialized('No connection to Renode')

    def run_robot_keyword(
            self,
            keyword: str,
            *args: Any,
            **kwargs: Any) -> str:
        """
        Executes Robot keyword using Robot server.

        Parameters
        ----------
        keyword : str
            Keyword to be run
        args : Any
            Keyword args
        kwargs : Any
            Keyword kwargs

        Returns
        -------
        str :
            Renode keyword output
        """
        if self.robot_connection is None:
            raise RobotUninitialized('No Robot connection')
        if keyword not in self.keywords:
            raise ValueError('Invalid keyword')

        keyword_args = list(args)
        keyword_args.extend([f'{k}={v}' for k, v in kwargs.items()])

        return self.robot_connection.run_keyword(keyword, keyword_args, None)

    def wait_until_log_contains(
            self,
            string: str,
            is_regex: bool = False,
            timeout: Optional[float] = None) -> bool:
        """
        Reads renode log and returns when log contains given string.

        Parameters
        ----------
        string : str
            String that is searched in log
        is_regex : bool
            If string should be interpreted as regex pattern
        timeout : Optional[float]
            Wait timeout, if None then assumed to be infinity

        Returns
        -------
        bool :
            True if string occurred in log, false if timeout is hit
        """
        log_buffer = ''
        start_time = time.perf_counter()

        if is_regex:
            pattern = re.compile(string)
            while pattern.match(log_buffer) is None:
                if (timeout is None and
                        time.perf_counter() - start_time > timeout):
                    return False
                if '\n' in log_buffer:
                    log_buffer = log_buffer[log_buffer.rindex('\n') + 1:]
                log_buffer += self.read_from_renode()
                time.sleep(.01)

        else:
            while string not in log_buffer:
                if (timeout is None and
                        time.perf_counter() - start_time > timeout):
                    return False
                if '\n' in log_buffer:
                    log_buffer = log_buffer[log_buffer.rindex('\n') + 1:]
                log_buffer += self.read_from_renode()
                if len(log_buffer):
                    print('_'*64)
                    print(log_buffer)
                time.sleep(.01)

        return True

    def _start_renode_process(self):
        """
        Starts Renode in background process.
        """
        logging.info('starting Renode process')
        # check if renode or renode-run exists in system
        renode_executable = None
        renode_args = []

        if self.renode_path is not None:
            if self.renode_path.is_file():
                renode_executable = str(self.renode_path)
        else:
            if shutil.which('renode') is not None:
                renode_executable = 'renode'
            elif shutil.which('renode-run') is not None:
                renode_executable = 'renode-run'
                renode_args.extend([
                    'exec',
                    '--'
                ])

        if renode_executable is None:
            raise FileNotFoundError('Renode executable not found')

        if self.telnet_port is None:
            pipe_in = os.pipe()
            self.renode_pipe_in = os.fdopen(pipe_in[1], 'w')

        pipe_out = os.pipe()
        os.set_blocking(pipe_out[0], False)
        self.renode_pipe_out = os.fdopen(pipe_out[0], 'r')

        renode_args.extend([
            '--plain',
            '--robot-server-port', str(self.robot_port)
        ])

        if self.telnet_port is not None:
            renode_args.extend([
                '--port', str(self.telnet_port),
                '--disable-xwt'
            ])
        else:
            renode_args.append(
                '--console'
            )

        self.renode_process = subprocess.Popen(
            [
                renode_executable,
                *renode_args
            ],
            stdin=pipe_in[0] if self.telnet_port is None else None,
            stdout=pipe_out[1]
        )
        logging.info(f'{self.renode_process=}')

        self.subprocess_pids.append(self.renode_process.pid)

        if renode_executable == 'renode-run':
            def get_renode_process_pid():
                renode_run_process = psutil.Process(self.renode_process.pid)
                children = renode_run_process.children(recursive=False)

                renode_process = next(
                    ps for ps in children if ps.name() == 'renode'
                )

                return renode_process.pid

            pid = self._retry_until_success(get_renode_process_pid)

            self.subprocess_pids.append(pid)
            self.renode_pid = pid

        else:
            self.renode_pid = self.renode_process.pid

        logging.info('Renode process started')

    def _open_telnet(self):
        """
        Opens telnet connection.
        """
        logging.info('opening telnet')
        self.telnet_connection = self._retry_until_success(
            telnetlib.Telnet,
            ['localhost', self.telnet_port],
            {'timeout': .5}
        )

        # check if telnet is properly connected
        _, matches, _ = self.telnet_connection.expect(
            ['(monitor)'.encode()],
            timeout=10
        )
        if matches is None:
            raise ConnectionError('Telnet connection error')

        logging.info('Telnet connected')

    def _open_robot(self):
        """
        Opens Robot connection.
        """
        logging.info('opening Robot connection')
        if self.robot_port == 0:
            def get_robot_port():
                robot_port_file = (Path(tempfile.gettempdir()) /
                                   f'renode-{self.renode_pid}' /
                                   'robot_port')
                if not robot_port_file.exists():
                    raise FileNotFoundError('Missing file with robot port')

                with open(robot_port_file, 'r') as f:
                    port_num_str = f.read()

                if not port_num_str.isnumeric():
                    raise ValueError(f'Invalid robot port: {port_num_str}')

                return int(port_num_str)

            robot_port = self._retry_until_success(get_robot_port)

            self.robot_port = robot_port

        self.robot_connection = self._retry_until_success(
            robot_remote.Remote,
            func_kwargs={
                'uri': f'http://0.0.0.0:{self.robot_port}',
                'timeout': 30.
            }
        )

        self.keywords = self.robot_connection.get_keyword_names()

        logging.info(f'Robot connected via port {self.robot_port}')

    @staticmethod
    def escape_ansi(line):
        ansi_escape = re.compile(r'(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]')
        return ansi_escape.sub('', line)

    @staticmethod
    def _retry_until_success(
            func,
            func_args: List[Any] = [],
            func_kwargs: Dict[str, Any] = {},
            retries=10,
            retry_time=1) -> Any:
        assert retries > 0

        while True:
            try:
                return func(*func_args, **func_kwargs)
            except Exception as e:
                retries -= 1
                if retries < 0:
                    logging.error(
                        f'{func.__name__} failed: {e}'
                    )
                    raise
                else:
                    logging.warning(
                        f'{func.__name__} failed: {e}, retries left: {retries}'
                    )
                time.sleep(retry_time)
