import asyncio
import contextlib
import io
import logging
import os
import signal
import socket
import ssl
import threading
import unittest
from test.support import TEST_HOME_DIR

import objc_asyncio
from objc_asyncio._log import logger

MAX_TEST_TIME = 30


@contextlib.contextmanager
def captured_log():
    try:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(fmt="%(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        yield stream

    finally:
        logger.removeHandler(handler)
        logger.setLevel(logging.NOTSET)


class TestCase(unittest.TestCase):
    def setUp(self):
        # Ensure the process is killed when a test takes
        # too much time.
        signal.alarm(MAX_TEST_TIME)

        self._old_policy = asyncio.get_event_loop_policy()
        asyncio.set_event_loop_policy(objc_asyncio.PyObjCEventLoopPolicy())
        self.loop = objc_asyncio.PyObjCEventLoop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        if self.loop._default_executor is not None:
            if self.loop.is_closed():
                self.loop._default_executor.shutdown(wait=True)
            else:
                self.loop.run_until_complete(self.loop.shutdown_default_executor())

        self.loop.close()
        asyncio.set_event_loop(None)
        asyncio.set_event_loop_policy(self._old_policy)
        signal.alarm(0)

    def make_socketpair(
        self, family=socket.AF_UNIX, type=socket.SOCK_STREAM, proto=0  # noqa: A002
    ):
        def close_socket(sd):
            try:
                sd.close()
            except socket.error:
                pass

        sd1, sd2 = socket.socketpair(family, type, proto)
        self.addCleanup(close_socket, sd1)
        self.addCleanup(close_socket, sd2)

        sd1.setblocking(False)
        sd2.setblocking(False)

        return sd1, sd2

    def make_echoserver(self, family=socket.AF_INET):
        sd_serv = socket.socket(family, socket.SOCK_STREAM, 0)
        sd_serv.listen(5)
        self.addCleanup(sd_serv.close)

        def runloop():
            try:
                while True:
                    sd, addr = sd_serv.accept()

                    data = sd.recv(100)
                    data = data.upper()
                    sd.sendall(data)
                    sd.close()

            except socket.error:
                pass

        thr = threading.Thread(target=runloop)
        thr.start()

        return sd_serv.getsockname()


class EchoServerProtocol(asyncio.Protocol):
    def connection_made(self, transport):
        self.transport = transport

    def data_received(self, data):
        self.transport.write(data.upper())
        self.transport.close()


ONLYCERT = os.path.join(TEST_HOME_DIR, "ssl_cert.pem")
ONLYKEY = os.path.join(TEST_HOME_DIR, "ssl_key.pem")
SIGNED_CERTFILE = os.path.join(TEST_HOME_DIR, "keycert3.pem")
SIGNING_CA = os.path.join(TEST_HOME_DIR, "pycacert.pem")
PEERCERT = {
    "OCSP": ("http://testca.pythontest.net/testca/ocsp/",),
    "caIssuers": ("http://testca.pythontest.net/testca/pycacert.cer",),
    "crlDistributionPoints": ("http://testca.pythontest.net/testca/revocation.crl",),
    "issuer": (
        (("countryName", "XY"),),
        (("organizationName", "Python Software Foundation CA"),),
        (("commonName", "our-ca-server"),),
    ),
    "notAfter": "Jul  7 14:23:16 2028 GMT",
    "notBefore": "Aug 29 14:23:16 2018 GMT",
    "serialNumber": "CB2D80995A69525C",
    "subject": (
        (("countryName", "XY"),),
        (("localityName", "Castle Anthrax"),),
        (("organizationName", "Python Software Foundation"),),
        (("commonName", "localhost"),),
    ),
    "subjectAltName": (("DNS", "localhost"),),
    "version": 3,
}


def simple_server_sslcontext():
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(ONLYCERT, ONLYKEY)
    server_context.check_hostname = False
    server_context.verify_mode = ssl.CERT_NONE
    return server_context


def simple_client_sslcontext(*, disable_verify=True):
    client_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client_context.check_hostname = False
    if disable_verify:
        client_context.verify_mode = ssl.CERT_NONE
    return client_context


def dummy_ssl_context():
    return ssl.SSLContext(ssl.PROTOCOL_TLS)
