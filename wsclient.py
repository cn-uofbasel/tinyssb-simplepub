import asyncio
from websockets.sync.client import connect

import tinyssb.keystore as keystore
import tinyssb.packet as packet
import _thread

HTTP_PORT = 8080


class CLIENT:
    
    def __init__(self, websocket):
        self.websocket = websocket
        self.ks = keystore.Keystore()
        self.fid = self.ks.new()                    # feed ID = public key
        self.pkt = packet.PACKET(self.fid, 1, self.fid[:20])
        print(f"fid = {self.fid}, {bytes(self.fid)}")
        # self.connection = http.client.HTTPConnection("127.0.0.1", HTTP_PORT, timeout=10)
        # _thread.start_new_thread(self.listener, tuple())

    def write(self, msg):
        print(f"Type = {type(self.fid)} + {self.fid}")
        self.pkt.mk_plain_entry(self.fid + bytes(msg, 'utf-8'), lambda mssg: self.ks.sign(self.fid, mssg))
        # Create connection and post the packet
        # with connect("ws://localhost:8765") as websocket:
        self.websocket.send(self.pkt.wire)
        # print(f"Received: {message}")
        # self.connection.request("POST", "/", self.pkt.wire)
        # print("{} sent".format(self.pkt.payload))

    def print_received(self, data):
        print("\n\n" + data)
        pkt = packet.from_bytes(data, self.fid, 1, self.fid[:20], lambda fid, mssg, sig: self.ks.verify(fid, mssg, sig))
        received = pkt.get_content().split(b'\x00')[0]
        print("Received: {}".format(received))
    
    def listener(self):
        while True:
            try:
                response = self.websocket.recv()
                # print("Status: {} and reason: {}".format(response.status, response.reason))
                self.print_received(response)
            except Exception as e:
                print(f"Error with {e}")

# def hello(msg="Hello world!"):
#     with connect(f"ws://localhost:{HTTP_PORT}") as websocket:
#         websocket.send(msg)
#         message = websocket.recv()
#         print(f"Received: {message}")

if __name__ == "__main__":
    try:
        with connect(f"ws://localhost:{HTTP_PORT}") as websocket:
            client = CLIENT(websocket)
            client.write("Hello world!")
            while True:
                msg = input(">>")
                client.write(msg)
                # websocket.send(msg)
                # hello(msg)
    except KeyboardInterrupt:
        print()
