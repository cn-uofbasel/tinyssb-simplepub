import asyncio
import websockets
from websockets.sync.client import connect
import time

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
        # print(f"fid = {self.fid}, {bytes(self.fid)}")
        # self.write("Hello world! 2")
        # self.write("HHHHHHHHHHHHHHHHHHHHHH")
        _thread.start_new_thread(self.listener, tuple())

    def write(self, msg):
        # time.sleep(1)
        # print(f"Type = {type(self.fid)} + {self.fid}")
        self.pkt.mk_plain_entry(self.fid + bytes(msg, 'utf-8'), lambda mssg: self.ks.sign(self.fid, mssg))
        # Create connection and post the packet
        self.websocket.send(self.pkt.wire)
        # print("{} sent".format(self.pkt.payload))

    def print_received(self, data):
        # pkt = packet.from_bytes(bytes(data), self.fid, 1, self.fid[:20], lambda fid, mssg, sig: self.ks.verify(fid, mssg, sig))
        # received = data.split(b'\x00')[0]
        # print(f"\nReceived: {data[:5]}")
        msg = data[40:].split(b'\x00')[0]
        print(f"\nReceived: {msg}\n")
    
    def listener(self):
        while True:
            try:
                response = self.websocket.recv()
                # print("Status: {}".format(response))
                self.print_received(response)
            except (websockets.ConnectionClosedOK, Exception) as e:
                print(f"Error with {e}")

if __name__ == "__main__":
    try:
        with connect(f"ws://localhost:{HTTP_PORT}") as websocket:
            client = CLIENT(websocket)
            # client.write("Hello world!")
            client.write("Hello world!")
            while True:
                msg = input(">>")
                client.write(msg)
                # websocket.send(msg)
                # hello(msg)
    except KeyboardInterrupt:
        print()