from ctypes import sizeof
import http.client
import keystore
import packet
import sys

from flask import Flask
from flask_sockets import Sockets

app = Flask(__name__)
sockets = Sockets(app)

HTTP_PORT = 8080

if __name__ == '__main__':

    # Create keystore, identity and packet
    ks = keystore.Keystore()
    fid = ks.new()                    # feed ID = public key
    pkt = packet.PACKET(fid, 1, fid[:20])
    if len(sys.argv) > 1:
        msg = bytes(' '.join(sys.argv[1:]), 'utf-8')
    else:
        msg = b"Hello!"
    print("That: {}, {}".format(sys.argv.count(sys.argv), sys.argv))
    pkt.mk_plain_entry(msg, lambda msg: ks.sign(fid, msg))

    # Create connection and post the packet
    connection = http.client.HTTPConnection("127.0.0.1", HTTP_PORT, timeout=10)
    connection.request("POST", "/", pkt.wire)
    print("{} sent".format(pkt.wire))

    # Get response (which is just the packet that is sent back)
    response =  connection.getresponse()
    print("Status: {} and reason: {}".format(response.status, response.reason))

    # Extract the data, reform the packet and check the signature
    data = response.read()
    pkt = packet.from_bytes(data, fid, 1, fid[:20], lambda fid, msg, sig: ks.verify(fid, msg, sig))
    received = pkt.get_content().split(b'\x00')[0]
    print("Received: {}".format(received))

    connection.close()
